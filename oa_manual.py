from collections import defaultdict

from time import time
from util import elapsed

# things to set here:
#       license, free_metadata_url, free_pdf_url
# free_fulltext_url is set automatically from free_metadata_url and free_pdf_url

def get_overrides_dict():
    override_dict = defaultdict(dict)

    # cindy wu example
    override_dict["10.1038/nature21360"]["free_pdf_url"] = "https://arxiv.org/pdf/1703.01424.pdf"

    # example from twitter
    override_dict["10.1021/acs.jproteome.5b00852"]["free_pdf_url"] = "http://pubs.acs.org/doi/pdfplus/10.1021/acs.jproteome.5b00852"

    return override_dict