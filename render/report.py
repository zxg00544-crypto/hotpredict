"""日报 Markdown。排序：快讯档 act_now -> rating -> score；趋势档 slope -> score。"""
from datetime import datetime

RATING_ORDER = {"A": 0, "B": 1, "C": 2}

def _row(i: int, t: dict) -> str:
    now = " ｜立即行动" if t.get("act_now") else ""
    hook = (t.get("hook_reason") or "").replace("\n", " ")
    return (f"| {i} | **{t.get('rating','?')}** | {t.get('title','')[:40]} | "
            f"{t.get('score',0)} | {t.get('G',0)} | {t.get('track','其他')} | "
            f"{hook}{now} | {t.get('url','')} |")

HEADER = ("| # | 评级 | 话题 | 分 | 增速G | 赛道 | 钩子/理由 | 链接 |\n"
          "|---|------|------|----|-------|------|-----------|------|")

def _fast_section(fast: list) -> str:
    if not fast:
        return "### 快讯档（1-6小时内）\n\n今日暂无热点进入快讯档。\n"
    rows = sorted(fast, key=lambda t: (not t.get("act_now", False),
                                       RATING_ORDER.get(t.get("rating"), 9),
                                       -t.get("score", 0)))
    lines = ["### 快讯档（1-6小时内）", "", HEADER]
    for i, t in enumerate(rows, 1):
        lines.append(_row(i, t))
        if t.get("angle"):
            lines.append(f"\n> 角度：{t['angle']}\n")
    return "\n".join(lines) + "\n"

def _trend_section(trend: list) -> str:
    if not trend:
        return "### 趋势推荐（3-7天窗口）\n\n今日暂无热点进入趋势推荐。\n"
    rows = sorted(trend, key=lambda t: (-t.get("slope", 0), -t.get("score", 0)))
    lines = ["### 趋势推荐（3-7天窗口）", "", HEADER]
    for i, t in enumerate(rows, 1):
        lines.append(_row(i, t))
        if t.get("angle"):
            lines.append(f"\n> 角度：{t['angle']}\n")
    return "\n".join(lines) + "\n"

def render_daily(date_str: str, fast: list, trend: list, meta: dict) -> str:
    head = [f"# 热点预判日报 · {date_str}", ""]
    head.append(f"- 采集源：{', '.join(meta.get('sources') or []) or '无'}")
    head.append(f"- 评级模型：{meta.get('llm_model','未运行')}"
                f"（备选切换 {meta.get('llm_fallback_count',0)} 次）")
    if meta.get("degraded"):
        head.append("- ⚠️ **本轮 LLM 降级**：以下只含机械评分分档，"
                    "没有 A/B/C 评级与角度，参考价值打折，请人工补判断")
    head += ["", f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             f"数据来源：`{meta.get('db_path','')}`", "",
             "---", "", _fast_section(fast), "---", "", _trend_section(trend),
             "---", "",
             "> 评级标准：A=genre≥8 且 fit≥7；B=genre≥6 或 fit≥8；C=其余。"
             "快讯档=1-6h 新热；趋势推荐=3-7d 连续上行。"]
    return "\n".join(head) + "\n"
