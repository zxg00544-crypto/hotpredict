"""六源连通性探针：逐源请求一次并解析，打印 PASS/FAIL/NEED_COOKIE。"""
import re, sys, requests
from collectors.base import Signal, topic_key

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

def normalize_title(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t or "", flags=re.UNICODE).lower()

def probe_zhihu_parse(payload: dict) -> list:
    out = []
    for i, item in enumerate(payload.get("data", []), 1):
        t = item.get("target") or {}
        digits = re.sub(r"\D", "", item.get("detail_text", "") or "") or "0"
        out.append(Signal(topic_key=topic_key(t.get("title", "")), source="zhihu",
                          title=t.get("title", ""),
                          url="https://www.zhihu.com/question/" + str(t.get("id", 0)),
                          heat=float(digits), rank=i, rank_delta=0, engagement=float(digits),
                          author_weight=0.6, published_at="", fetched_at="", raw=item))
    return out

def probe_zhihu(cfg):
    r = requests.get("https://api.zhihu.com/topstory/hot-list", headers=UA, timeout=10)
    sigs = probe_zhihu_parse(r.json())
    return {"status": "PASS" if sigs else "FAIL", "n": len(sigs),
            "sample": sigs[0].title if sigs else ""}

def probe_bilibili(cfg):
    r = requests.get("https://api.bilibili.com/x/web-interface/search/square?limit=10",
                     headers=UA, timeout=10)
    d = r.json().get("data", {})
    rows = d.get("list") or d.get("trending", {}).get("list", []) or []
    return {"status": "PASS" if rows else "FAIL", "n": len(rows),
            "sample": str(rows[0].get("keyword") or rows[0].get("title") or "") if rows else ""}

def probe_weibo(cfg):
    cookie = str(cfg.get("weibo_cookie") or "").strip()
    if not cookie:
        return {"status": "NEED_COOKIE", "n": 0, "sample": ""}
    h = dict(UA); h["Cookie"] = cookie
    r = requests.get("https://m.weibo.cn/api/container/getIndex?containerid=106003type%3D25%26t%3D3%26disable_hot%3D1%26filter_type%3Drealtimehot",
                     headers=h, timeout=10)
    cards = r.json().get("data", {}).get("cards", [])
    n = sum(len(c.get("card_group", [])) for c in cards)
    return {"status": "PASS" if n else "FAIL", "n": n, "sample": "weibo container"}

def probe_hn(cfg):
    r = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json",
                     headers=UA, timeout=10)
    ids = r.json()[:30]
    return {"status": "PASS" if ids else "FAIL", "n": len(ids), "sample": "hn top"}

def probe_reddit(cfg):
    r = requests.get("https://www.reddit.com/r/popular.json?limit=10", headers=UA, timeout=10)
    ch = r.json().get("data", {}).get("children", [])
    return {"status": "PASS" if ch else "FAIL", "n": len(ch),
            "sample": ch[0]["data"]["title"] if ch else ""}

def probe_github(cfg):
    r = requests.get("https://github.com/trending", headers=UA, timeout=15)
    blocks = re.findall(r'<article class="Box-row">([\s\S]*?)</article>', r.text)
    pat = re.compile(r'<h2[^>]*>[\s\S]*?<a[^>]*href="/([^"]+)"')
    n = sum(1 for b in blocks if pat.search(b))
    return {"status": "PASS" if n >= 5 else "FAIL", "n": n, "sample": "github trending html"}

PROBES = {"zhihu": probe_zhihu, "bilibili": probe_bilibili, "weibo": probe_weibo,
          "hn": probe_hn, "reddit": probe_reddit, "github": probe_github}

def probe_all(cfg: dict) -> dict:
    out = {}
    for name, fn in PROBES.items():
        if not cfg.get("platforms", {}).get(name, False):
            out[name] = {"status": "OFF", "n": 0, "sample": ""}
            continue
        try:
            out[name] = fn(cfg)
        except Exception as e:
            out[name] = {"status": "FAIL", "n": 0,
                         "sample": type(e).__name__ + ": " + str(e)[:80]}
    return out

def build_payload_md(res: dict) -> str:
    lines = ["# 六源连通性探针报告", ""]
    for k, v in res.items():
        lines.append(f"| {k} | {v['status']} | n={v['n']} | {str(v.get('sample',''))[:60]} |")
    ok = sum(1 for v in res.values() if v["status"] == "PASS")
    lines += ["", f"TOTAL PASS={ok}/{len(res)}"]
    return "\n".join(lines) + "\n"

if __name__ == "__main__":
    import yaml
    cfg = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "config.yaml",
                              encoding="utf-8"))
    res = probe_all(cfg)
    for k, v in res.items():
        print(f"{k:10s} {v['status']:10s} n={v['n']:<4} {str(v['sample'])[:50]}")
    ok = sum(1 for v in res.values() if v["status"] == "PASS")
    print(f"TOTAL PASS={ok}/{len(res)}")
    sys.exit(0 if ok >= 4 else 1)
