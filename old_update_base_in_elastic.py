import os
import sickle
import boto
import datetime
import requests
from time import sleep
from time import time
from util import elapsed
import logging
import zlib
import re
import json
import sys
import random
import argparse
from elasticsearch import Elasticsearch, RequestsHttpConnection, compat, exceptions
from elasticsearch.helpers import parallel_bulk
from elasticsearch.helpers import bulk
from elasticsearch.helpers import scan
from multiprocessing import Process
from multiprocessing import Queue
from multiprocessing import Pool
from HTMLParser import HTMLParser


import oa_local
from oa_base import get_urls_from_our_base_doc
from publication import call_targets_in_parallel
from webpage import WebpageInUnknownRepo
from util import JSONSerializerPython2


# set up elasticsearch
INDEX_NAME = "base"
TYPE_NAME = "record"



libraries_to_mum = [
    "requests.packages.urllib3",
    "requests_oauthlib",
    "stripe",
    "oauthlib",
    "boto",
    "newrelic",
    "RateLimiter",
    "elasticsearch",
    "urllib3"
]

for a_library in libraries_to_mum:
    the_logger = logging.getLogger(a_library)
    the_logger.setLevel(logging.WARNING)
    the_logger.propagate = True



def set_up_elastic(url):
    if not url:
        url = os.getenv("BASE_URL")
    es = Elasticsearch(url,
                       serializer=JSONSerializerPython2(),
                       retry_on_timeout=True,
                       max_retries=100)
    return es





def save_records_in_es(es, records_to_save, threads, chunk_size):
    start_time = time()

    # have to do call parallel_bulk in a for loop because is parallel_bulk is a generator so you have to call it to
    # have it do the work.  see https://discuss.elastic.co/t/helpers-parallel-bulk-in-python-not-working/39498
    if threads > 1:
        for success, info in parallel_bulk(es,
                                           actions=records_to_save,
                                           refresh=True,
                                           request_timeout=60,
                                           thread_count=threads,
                                           chunk_size=chunk_size):
            if not success:
                print("A document failed:", info)
    else:
        for success_info in bulk(es, actions=records_to_save, refresh=True, request_timeout=60, chunk_size=chunk_size):
            pass
    print u"done sending {} records to elastic in {} seconds".format(len(records_to_save), elapsed(start_time, 4))
    # print records_to_save[0]



query_dict = {
  "size": 100,
  "from": 0,
  "query": {
    "bool": {
      "must_not": [
        {
          "exists": {
            "field": "fulltext_url_dicts"
          }
        }
        ],
      "must": [
        {
          "match": {
            "oa": 2
          }
        },
        {
          "range": {
            "fulltext_last_updated": {"le": "2017-02-13"}
            }
        }
      ]
    }
  },
  "sort": [
    {
      "random": "asc"
    }
  ]
}


class BaseResult(object):
    def __init__(self, doc):
        self.doc = doc
        self.fulltext_last_updated = datetime.datetime.utcnow().isoformat()
        self.fulltext_url_dicts = []
        self.license = None
        self.set_webpages()


    def scrape_for_fulltext(self):
        if self.doc["oa"] == 1:
            return

        response_webpages = []

        found_open_fulltext = False
        for my_webpage in self.webpages:
            if not found_open_fulltext:
                my_webpage.scrape_for_fulltext_link()
                if my_webpage.has_fulltext_url:
                    print u"** found an open version! {}".format(my_webpage.fulltext_url)
                    found_open_fulltext = True
                    response_webpages.append(my_webpage)

        self.open_webpages = response_webpages
        sys.exc_clear()  # someone on the internet said this would fix All The Memory Problems. has to be in the thread.
        return self

    def set_webpages(self):
        self.open_webpages = []
        self.webpages = []
        for url in get_urls_from_our_base_doc(self.doc):
            my_webpage = WebpageInUnknownRepo(url=url)
            self.webpages.append(my_webpage)


    def set_fulltext_urls(self):

        # first set license if there is one originally.  overwrite it later if scraped a better one.
        if "license" in self.doc and self.doc["license"]:
            self.license = oa_local.find_normalized_license(self.doc["license"])

        for my_webpage in self.open_webpages:
            if my_webpage.has_fulltext_url:
                response = {}
                self.fulltext_url_dicts += [{"free_pdf_url": my_webpage.scraped_pdf_url, "pdf_landing_page": my_webpage.url}]
                if not self.license or self.license == "unknown":
                    self.license = my_webpage.scraped_license
            else:
                print "{} has no fulltext url alas".format(my_webpage)

        if self.license == "unknown":
            self.license = None


    def make_action_record(self):

        doc = self.doc

        update_fields = {
            "random": random.random(),
            "fulltext_last_updated": self.fulltext_last_updated,
            "fulltext_url_dicts": self.fulltext_url_dicts,
            "fulltext_license": self.license,
        }

        doc.update(update_fields)
        action = {"doc": doc}
        action["_id"] = self.doc["id"]
        action["_op_type"] = "update"
        action["_type"] = TYPE_NAME
        action["_index"] = INDEX_NAME
        action["_retry_on_conflict"] = 3
        action["doc_as_upsert"] = True
        # print "\n", action
        return action

def find_fulltext_for_base_hits(hits):
    records_to_save = []
    base_results = []

    for base_hit in hits:
        base_results.append(BaseResult(base_hit))

    scrape_start = time()

    targets = [base_result.scrape_for_fulltext for base_result in base_results]
    call_targets_in_parallel(targets)
    print u"scraping {} webpages took {} seconds".format(len(base_results), elapsed(scrape_start, 2))

    for base_result in base_results:
        base_result.set_fulltext_urls()
        records_to_save.append(base_result.make_action_record())

    return records_to_save


def do_a_loop(first=None, last=None, url=None, threads=0, chunk_size=None):
    loop_start = time()
    es = set_up_elastic(url)

    search_results = es.search(index=INDEX_NAME, body=query_dict, request_timeout=10000)
    # print u"search body:\n{}".format(query)
    print u"took {} seconds to search ES".format(elapsed(loop_start, 2))

    # decide if should stop looping after this
    if not search_results["hits"]["hits"]:
        print "no hits!  exiting"
        sys.exit()

    base_records = [base_hit["_source"] for base_hit in search_results["hits"]["hits"]]
    records_to_save = find_fulltext_for_base_hits(base_records)
    save_records_in_es(es, records_to_save, threads, chunk_size)

    print "** took {} seconds to do {}, {:,} remaining\n".format(
        elapsed(loop_start, 2), len(records_to_save), search_results["hits"]["total"])




def run():
    has_more_records = True
    while has_more_records:
        pool_time = time()
        my_process = Process(target=do_a_loop)
        my_process.daemon = True
        my_process.start()
        my_process.join()
        my_process.terminate()
        # print u"took {} seconds for do_a_loop".format(elapsed(pool_time, 2))




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run stuff.")


    # just for updating lots
    function = run

    parsed = parser.parse_args()

    print u"calling {} with these args: {}".format(function.__name__, vars(parsed))
    function(**vars(parsed))


# 60,870,228 at 12:38pm on friday