#! /usr/bin/python3

# Extract captured pages from the database.

import os
import psycopg2
import zlib
import json
from html_extractor import ExtractedContent

class CapturedPage:
    """A page as captured from a particular locale.  Corresponds to one
       row of the .captured_pages table.  Not tied to the database.
    """

    def __init__(self, locale, url, access_time, result, detail,
                 redir_url, capture_log, html_content, screenshot):

        self.locale      = locale
        self.url         = url
        self.access_time = access_time
        self.result      = result
        self.detail      = detail
        self.redir_url   = redir_url
        self.screenshot  = screenshot

        # For memory efficiency, the compressed data is only
        # uncompressed upon request.  (screenshot, if available, is
        # internally compressed - but is directly usable that way,
        # being a PNG.)
        self._capture_log = capture_log
        self._capture_log_unpacked = False

        self._html_content = html_content
        self._html_content_unpacked = False

        # Derived values.
        self._extracted = None

    def _do_extraction(self):
        if self._extracted is None:
            self._extracted = ExtractedContent(self.redir_url,
                                               self.html_content)

    @property
    def capture_log(self):
        if not self._capture_log_unpacked:
            self._capture_log = json.loads(
                zlib.decompress(self._capture_log).decode("utf-8"))
            self._capture_log_unpacked = True
        return self._capture_log

    @property
    def html_content(self):
        if not self._html_content_unpacked:
            self._html_content = (
                zlib.decompress(self._html_content).decode("utf-8"))
            self._html_content_unpacked = True
        return self._html_content

    @property
    def text_content(self):
        self._do_extraction()
        return self._extracted.text_content

    @property
    def resources(self):
        self._do_extraction()
        return self._extracted.resources

    @property
    def links(self):
        self._do_extraction()
        return self._extracted.links

    def dump(self, fp, *,
             capture_log=False,
             html_content=False,
             text_content=False,
             resources=False,
             links=False):
        val = {
            "0_url": self.url,
            "1_locale": self.locale,
            "2_access_time": self.access_time.isoformat(' '),
            "3_result": self.result,
            "4_detail": self.detail,
            "5_redir": None,
            "6_log": None,
            "7_html": None,
            "7_text": None,
            "7_rsrcs": None,
            "7_links": None
        }
        if self.redir_url != self.url:
            val["5_redir"] = self.redir_url

        if capture_log:  val["6_log"]   = self.capture_log
        if html_content: val["7_html"]  = self.html_content
        if text_content: val["7_text"]  = self.text_content
        if resources:    val["7_rsrcs"] = self.resources
        if links:        val["7_links"] = self.links

        fp.write(json.dumps(val, sort_keys=True).encode("utf-8"))
        fp.write(b'\n')

class PageDB:
    """Wraps a database handle and knows how to extract pages or other
       interesting material (add queries as they become useful!)"""

    def __init__(self, connstr):
        self.db = psycopg2.connect(connstr)

    def get_pages(self, *,
                  ordered=False,
                  where_clause="",
                  limit=None):
        """Retrieve pages from the database matching the where_clause.
           This is a generator, which produces one CapturedPage object
           per row.
        """

        query = ("SELECT c.locale, u.url, c.access_time, c.result, d.detail,"
                 "       r.url, c.capture_log, c.html_content, c.screenshot"
                 "       FROM captured_pages c"
                 "  LEFT JOIN url_strings u    ON c.url = u.id"
                 "  LEFT JOIN url_strings r    ON c.redir_url = r.id"
                 "  LEFT JOIN capture_detail d ON c.detail = d.id")

        if where_clause:
            query += "  WHERE {}".format(where_clause)

        if ordered:
            query += "  ORDER BY u.url, c.locale"

        if limit is not None:
            query += "  LIMIT {}".format(limit)

        # This must be a named cursor, otherwise psycopg2 helpfully fetches
        # ALL THE ROWS AT ONCE, and they don't fit in RAM and it crashes.
        with self.db, \
             self.db.cursor("pagedb_qtmp_{}".format(os.getpid())) as cur:
            cur.itersize = 100
            cur.execute(query)
            for row in cur:
                yield CapturedPage(*row)

if __name__ == '__main__':
    def main():
        import argparse
        import sys
        import subprocess

        ap = argparse.ArgumentParser(
            description="Dump out captured HTML pages."
        )
        ap.add_argument("database", help="Database to connect to")
        ap.add_argument("where", help="WHERE clause for query", nargs='*')
        ap.add_argument("--limit", help="maximum number of results",
                        default=None)
        ap.add_argument("--html", help="also dump the captured HTML",
                        action="store_true")
        ap.add_argument("--links", help="also dump extracted hyperlinks",
                        action="store_true")
        ap.add_argument("--resources", help="also dump extracted resource URLs",
                        action="store_true")
        ap.add_argument("--text", help="also dump extracted text",
                        action="store_true")
        ap.add_argument("--capture-log", help="also dump the capture log",
                        action="store_true")
        ap.add_argument("--ordered", help="sort pages by URL and then locale",
                        action="store_true")

        args = ap.parse_args()
        args.where = " ".join(args.where)

        if "=" not in args.database:
            args.database = "dbname="+args.database

        db = PageDB(args.database)
        prettifier = subprocess.Popen(["underscore", "pretty"],
                                      stdin=subprocess.PIPE)

        prettifier.stdin.write(b'[')

        for page in db.get_pages(where_clause = args.where,
                                 limit        = args.limit,
                                 ordered      = args.ordered):
            page.dump(prettifier.stdin,
                      html_content = args.html,
                      text_content = args.text,
                      links        = args.links,
                      resources    = args.resources,
                      capture_log  = args.capture_log)
            prettifier.stdin.write(b',')
            prettifier.stdin.flush()

        prettifier.stdin.write(b']')
        prettifier.stdin.close()

    main()
