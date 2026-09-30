# -*- coding: utf-8 -*-
"""URL 净化：只对"查询参数纯属追踪"的域名去 query。

头条热榜返回的链接带一长串 log_pb/rank/style_id/topic_id 埋点参数，
推送/日报/看板里既难看又无用（2026-09-30 用户点名）。
百度(top.baidu.com/board?tab=)、微博(s.weibo.com/weibo?q=)等源的 query
承载真实内容，保持原样 —— 用域名白名单控制，勿全局截断。
"""
from urllib.parse import urlsplit, urlunsplit

# 需要去 query 的域名（含子域）：host == 域 或 host.endswith(".域")
STRIP_QUERY_HOSTS = ("toutiao.com",)


def clean_url(u) -> str:
    if not u:
        return u or ""
    u = str(u)
    try:
        parts = urlsplit(u)
    except ValueError:
        return u
    host = (parts.hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in STRIP_QUERY_HOSTS):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return u
