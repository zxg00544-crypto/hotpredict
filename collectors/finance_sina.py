"""新浪财经7x24电报（财联社免签替代源：财联社API需sha1签名，实测10012）。"""
import re, time, requests
from collectors.base import Signal, topic_key
from probe import UA

URL = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=152"

def _title(text: str) -> str:
    m = re.search(r"【(.+?)】", text or "")
    if m and m.group(1).strip():
        return m.group(1).strip()[:60]
    return re.sub(r"\s+", " ", text or "").strip()[:40]

def parse_feed(payload: dict, fetched_at: str) -> list[Signal]:
    out = []
    feed = (((payload.get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
    for i, item in enumerate(feed, 1):
        text = item.get("rich_text") or ""
        if not text:
            continue
        title = _title(text)
        like = float(item.get("like_nums") or 0)
        heat = max(like, 200.0 - i * 4.0)
        out.append(Signal(topic_key=topic_key(title), source="finance_sina", title=title,
                          url=item.get("docurl") or "https://zhibo.sina.com.cn/",
                          heat=heat, rank=i, rank_delta=0, engagement=heat,
                          author_weight=0.8,
                          published_at=str(item.get("create_time") or ""),
                          fetched_at=fetched_at,
                          raw={"id": item.get("id"), "text": text[:200]}))
    return out

def fetch(cfg: dict) -> list[Signal]:
    r = requests.get(URL, headers=UA, timeout=10)
    r.raise_for_status()
    return parse_feed(r.json(), time.strftime("%Y-%m-%dT%H:%M:%S"))
