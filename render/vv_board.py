# -*- coding: utf-8 -*-
"""大V动向独立板块（阶段一，2026-10-05 用户批准）。

只读 signals 表出独立文件 + 钉钉 TopN（push_top），不参与评分/推送管道（不改
scoring/buckets/push_policy）。筛选：近 window_hours 内大V源 → heat 降序
→ 每人（微博 uid）≤3 → url 去重 → Top N。节流三闸：同 sig 不重推、
每日 max_push_per_day 次上限、跨日重置。

signals 表无 raw 列，取不到 screen_name，"每人"用 url 第三段 uid 判定：
https://weibo.com/{uid}/{bid}。vv 参数全部带代码内默认值（云端 config 来自
secret，本地 config.yaml 的键云端不会有）。

窗口按 published_at 发布时间过滤；解析失败回退抓取时间（2026-10-07 用户定）。"""
import datetime
from email.utils import parsedate_to_datetime

from urlclean import clean_url

DEFAULTS = {"window_hours": 24, "per_author": 3, "file_top": 10,
            "push_top": 10, "max_push_per_day": 3}
VV_SOURCES = ("weibo_v",)
EMPTY_MSG = "今日暂无大V博文"


def vv_cfg(cfg: dict) -> dict:
    """合并 config.vv 与默认值；缺键/空块/坏值一律回落默认。"""
    c = dict(DEFAULTS)
    for k, v in (cfg.get("vv") or {}).items():
        if k in DEFAULTS:
            try:
                c[k] = int(v)
            except (TypeError, ValueError):
                c[k] = DEFAULTS[k]
    return c


def _uid(url: str) -> str:
    parts = (url or "").split("/")
    if len(parts) >= 5 and "weibo.com" in (parts[2] or ""):
        return parts[3]
    return url or ""


def _published_dt(s):
    """解析微博 RFC822 风格发布时间；失败/空 → None（回退抓取时间口径）。

    用 email.utils.parsedate_to_datetime（locale 无关），勿用 strptime 的
    %a %b——Windows 中文 locale 下会解析失败。"""
    if not s:
        return None
    try:
        return parsedate_to_datetime(str(s))
    except (TypeError, ValueError):
        return None


def fetch_rows(conn, window_hours: int) -> list:
    """近 N 小时大V信号，按 heat 降序；只取可入表展示的列。

    窗口按 published_at 发布时间过滤：解析成功且早于窗口 → 丢弃；解析失败
    → 保留（回退抓取时间口径）。SQL 的 fetched_at 仍作廉价预筛兼停摆兜底。
    """
    cutoff = (datetime.datetime.now().astimezone()
              - datetime.timedelta(hours=int(window_hours)))
    cutoff_iso = cutoff.isoformat()
    marks = ",".join("?" * len(VV_SOURCES))
    rows = conn.execute(
        "SELECT title,url,heat,fetched_at,published_at,topic_key FROM signals "
        f"WHERE source IN ({marks}) AND fetched_at>=? "
        "ORDER BY heat DESC",
        (*VV_SOURCES, cutoff_iso)).fetchall()
    out = []
    for r in rows:
        pub = _published_dt(r["published_at"])
        if pub is not None and pub.tzinfo is not None and pub < cutoff:
            continue
        out.append(dict(r))
    return out


def select_top(rows: list, c: dict) -> list:
    """heat 降序 → 每人≤per_author → url 去重 → 截断 file_top。"""
    rows = sorted(rows, key=lambda r: float(r.get("heat") or 0), reverse=True)
    limit = int(c.get("file_top", DEFAULTS["file_top"]))
    per_limit = int(c.get("per_author", DEFAULTS["per_author"]))
    out, seen, per = [], set(), {}
    for r in rows:
        u = clean_url(r.get("url") or "")
        if not u or u in seen:
            continue
        a = _uid(u)
        if per.get(a, 0) >= per_limit:
            continue
        seen.add(u)
        per[a] = per.get(a, 0) + 1
        out.append({**r, "url": u})
        if len(out) >= limit:
            break
    return out


def _author(url: str) -> str:
    return _uid(url) or "-"


def _cell(text) -> str:
    return str(text or "").replace("|", "¦").replace("\n", " ").strip()


def render_vv(items: list, date_str: str, meta: dict) -> str:
    hours = int(meta.get("window_hours", DEFAULTS["window_hours"]))
    per = int(meta.get("per_author", DEFAULTS["per_author"]))
    head = [f"# 大V动向 {date_str}", ""]
    if not items:
        return "\n".join(head + [EMPTY_MSG, ""])
    head[0] = f"# 大V动向 {date_str}（Top{len(items)}，近{hours}h）"
    lines = head + ["", "| # | 账号 | 博文 | 互动heat | 时间 |",
                    "|---|------|------|---------|------|"]
    for i, it in enumerate(items, 1):
        when = str(it.get("published_at") or it.get("fetched_at") or "")[:19]
        lines.append(f"| {i} | {_author(it.get('url'))} | "
                     f"{_cell(it.get('title'))} | {int(it.get('heat') or 0)} | "
                     f"{when} |")
    srcs = ", ".join(meta.get("sources") or []) or "无"
    lines += ["", f"- 数据源：{srcs} · 窗口{hours}h · 每人≤{per}条"
                  f" · 生成 {date_str}"]
    return "\n".join(lines) + "\n"


def plan_vv_push(items: list, state: dict, date_str: str, c: dict) -> tuple:
    """返回 (是否推送, 标题, 内容)。空数据不推；同 sig 不重推；每日封顶。
    state 就地更新，调用方负责 save_state。"""
    if not items:
        return False, "", ""
    maxn = int(c.get("max_push_per_day", DEFAULTS["max_push_per_day"]))
    if state.get("vv_date") != date_str:
        state["vv_date"] = date_str
        state["vv_count"] = 0
        state["vv_sig"] = ""
    sig = "|".join(str(i.get("url") or "") for i in items)
    if sig == state.get("vv_sig"):
        return False, "", ""
    if int(state.get("vv_count") or 0) >= maxn:
        return False, "", ""
    lines = ["近24h 互动量最高（每人≤3条）："]
    for i, it in enumerate(items, 1):
        title = _cell(it.get("title"))
        lines.append(f"{i}. {_author(it.get('url'))} · {title} "
                     f"— {int(it.get('heat') or 0)}")
        if it.get("url"):
            lines.append(str(it["url"]))
    state["vv_sig"] = sig
    state["vv_count"] = int(state.get("vv_count") or 0) + 1
    return True, f"大V动向 Top{len(items)}", "\n".join(lines)
