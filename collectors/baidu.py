"""百度热搜（社会热点主力源：页面内嵌 s-data JSON，免签）。
财联社电报 API 需 sha1 签名（errno=10012 实测），以本源+头条热榜替代。"""
import re, json, time, requests
from collectors.base import Signal, topic_key
from probe import UA

URL = "https://top.baidu.com/board?tab=realtime"
_SDATA = re.compile(r"<!--s-data:(.*?)-->", re.S)


def parse_page(html: str, fetched_at: str) -> list[Signal]:
    m = _SDATA.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    cards = (data.get("data") or {}).get("cards") or []
    if not cards:
        return []
    out = []
    for i, item in enumerate(cards[0].get("content") or [], 1):
        title = (item.get("word") or "").strip()
        if not title:
            continue
        # 同 finance_sina 量纲：200-4*rank，不撞 heat_high=200，登顶靠 rank<=5。
        heat = 200.0 - i * 4.0
        out.append(Signal(topic_key=topic_key(title), source="baidu", title=title,
                          url=item.get("url") or "https://top.baidu.com/board?tab=realtime",
                          heat=heat, rank=i, rank_delta=0, engagement=heat,
                          author_weight=0.8,
                          fetched_at=fetched_at,
                          raw={"index": item.get("index"),
                               "hot": item.get("hotScore"),
                               "desc": (item.get("desc") or "")[:160]}))
    return out


def fetch(cfg: dict) -> list[Signal]:
    r = requests.get(URL, headers=UA, timeout=10)
    r.raise_for_status()
    return parse_page(r.text, time.strftime("%Y-%m-%dT%H:%M:%S"))
