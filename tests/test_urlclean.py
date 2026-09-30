# -*- coding: utf-8 -*-
import unittest

from urlclean import clean_url

DIRTY = ("https://www.toutiao.com/trending/7690769628993323049/"
         "?category_name=topic_innerflow&event_type=hot_board"
         "&log_pb=%7B%22category_name%22%3A%22topic_innerflow%22%7D"
         "&rank=&style_id=40132&topic_id=7690769628993323049")
CLEAN = "https://www.toutiao.com/trending/7690769628993323049/"


class TestCleanUrl(unittest.TestCase):
    def test_toutiao_query_stripped(self):
        self.assertEqual(clean_url(DIRTY), CLEAN)

    def test_toutiao_subdomain_stripped(self):
        self.assertEqual(clean_url("https://m.toutiao.com/article/x?id=1&t=2"),
                         "https://m.toutiao.com/article/x")

    def test_baidu_query_kept(self):
        u = "https://top.baidu.com/board?tab=realtime"
        self.assertEqual(clean_url(u), u)

    def test_weibo_query_kept(self):
        u = "https://s.weibo.com/weibo?q=%E6%A0%B8%E6%AD%A6%E5%99%A8"
        self.assertEqual(clean_url(u), u)

    def test_empty_and_plain(self):
        self.assertEqual(clean_url(""), "")
        self.assertEqual(clean_url(None), "")
        self.assertEqual(clean_url(CLEAN), CLEAN)


if __name__ == "__main__":
    unittest.main()
