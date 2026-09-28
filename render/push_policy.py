"""推送策略（设计 5.2 / L290-292，免费档 5 条/天上限）：
1) 日报：当天首跑推摘要（前3条A级+看板路径），1 条/天
2) A级快讯：新出现 rating=A 的话题合并单推，<=2 条/天
3) 降级/异常：告警 1 条/天
合计上限 4 条/天。state 按日重置，调用方推送后 save_state。"""
import json, os


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path: str, state: dict) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def _daily_digest(date_str, fast, trend, board_path):
    lines = [f"快讯 {len(fast)} 条 · 趋势 {len(trend)} 条"]
    top = [t for t in fast if t.get("rating") == "A"][:3]
    if top:
        lines.append("前3条A级：")
        for i, t in enumerate(top, 1):
            reason = (t.get("angle") or t.get("hook_reason") or "").strip()
            lines.append(f"{i}. {t.get('title', '')} —— {reason[:60]}")
    else:
        lines.append("今日暂无A级。")
    lines.append(f"看板：{board_path}")
    return "\n".join(lines)


def _a_digest(topic):
    parts = [topic.get("title", "")]
    if topic.get("track"):
        parts.append(f"方向：{topic['track']}")
    if topic.get("angle"):
        parts.append(f"角度：{topic['angle']}")
    if topic.get("hook_reason"):
        parts.append(f"理由：{topic['hook_reason']}")
    if topic.get("url"):
        parts.append(topic["url"])
    return "\n".join(parts)


def plan_push(state, date_str, fast, trend, degraded, failed, board_path):
    """生成待推送 [(kind, title, content)] 并原地更新 state。kind: daily/a/alert。"""
    if state.get("date") != date_str:
        state.clear()
        state.update({"date": date_str, "daily_done": False,
                      "a_count": 0, "pushed_a": [], "alert_date": ""})
    msgs = []
    if not state.get("daily_done"):
        state["daily_done"] = True
        msgs.append(("daily", f"热点预判 {date_str}",
                     _daily_digest(date_str, fast, trend, board_path)))
    if state.get("a_count", 0) < 2:
        pushed = state.setdefault("pushed_a", [])
        for t in fast:
            if state["a_count"] >= 2:
                break
            if t.get("rating") == "A" and t.get("key") not in pushed:
                pushed.append(t.get("key"))
                state["a_count"] += 1
                msgs.append(("a", f"快讯·A级 {t.get('title', '')}", _a_digest(t)))
    if (degraded or failed) and state.get("alert_date") != date_str:
        state["alert_date"] = date_str
        detail = []
        if failed:
            detail.append("失败源：" + ", ".join(failed))
        if degraded:
            detail.append("LLM降级（评级为机械分档）")
        msgs.append(("alert", f"热点预判告警 {date_str}", "\n".join(detail)))
    return msgs
