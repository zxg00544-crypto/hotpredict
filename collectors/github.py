"""GitHub Trending：抓 HTML，按 Box-row 块解析 /owner/repo（新结构，旧 itemprop 正则已失效）。"""
import re, time, requests
from collectors.base import Signal, topic_key
from probe import UA

BLOCK_RE = re.compile(r'<article class="Box-row">([\s\S]*?)</article>')
REPO_RE = re.compile(r'<h2[^>]*>[\s\S]*?<a[^>]*href="/([^"]+)"')

def parse_trending(html: str, fetched_at: str) -> list[Signal]:
    out = []
    for i, block in enumerate(BLOCK_RE.findall(html), 1):
        m = REPO_RE.search(block)
        if not m:
            continue
        repo = m.group(1).strip("/")
        out.append(Signal(topic_key=topic_key(repo.replace("-", " ")), source="github",
                          title=repo, url="https://github.com/" + repo,
                          heat=float(max(0, 200 - i * 6)), rank=i, rank_delta=0,
                          engagement=float(max(0, 200 - i * 6)), author_weight=0.5,
                          fetched_at=fetched_at, raw={"repo": repo}))
    return out

def fetch(cfg: dict) -> list[Signal]:
    r = requests.get("https://github.com/trending", headers=UA, timeout=15)
    r.raise_for_status()
    return parse_trending(r.text, time.strftime("%Y-%m-%dT%H:%M:%S"))
