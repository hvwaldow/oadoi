web: gunicorn views:app -w 3 --timeout 60 --reload
RQ_worker_queue_0: python rq_worker.py 0
RQ_worker_queue_1: python rq_worker.py 1
base_find_fulltext: python update.py Base.find_fulltext --chunk=10 --limit=10000000
run_with_realtime_scraping: python update.py Crossref.run_with_realtime_scraping --chunk=10 --limit=100000000
skip_all_hybrid: python update.py Crossref.run_with_skip_all_hybrid --chunk=10 --limit=100000000
load_test: python load_test.py --limit=50000
