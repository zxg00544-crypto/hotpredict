"""推送策略（钉钉免费无限条，按质控噪；设计 5.2）：
1) ⚡突发：独立信号即时直推，不等 LLM 评级，按 key 去重（kind=breaking）
2) A级攒批择优：每 4 小时窗口从新增 A 中挑分数最高 1 条推（kind=a），
   不即时、不先到先得，其余 A 留存到 21:00 晚报兜底
3) 日报摘要：21:00 后首轮推全天最佳汇总（含当日全部 A 级），1 条/天（kind=daily）
4) 降级/异常：告警 1 条/天（kind=alert）
B/C 不打扰。state 按日重置，跨日保留 a_pending/pushed 防丢防重；调用方推送后 save_state。
hour：当前小时（None=晚报立即允许、攒批立即执行，向后兼容）。"""
import json, os


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path: str, state: dict) -> None:
    """原子写：同目录临时文件写全 → os.replace 覆盖。
    序列化/写入失败：删除临时文件、原文件逐字节保持原样、异常上抛（不吞）。
    先序列化再落盘，避免异常在 open(path,'w') 截断原文件后才发生。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    blob = json.dumps(state, ensure_ascii=False, indent=1)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _daily_digest(date_str, fast, trend, board_path, a_seen):
    lines = [f"快讯 {len(fast)} 条 · 趋势 {len(trend)} 条"]
    seen = sorted((t for t in a_seen.values()),
                  key=lambda t: t.get("score", 0), reverse=True)
    rest = [t for t in fast if t.get("rating") != "A"]
    if not seen:
        lines.append("今日暂无A级，前3条高分快讯：")
        top = rest[:3]
    else:
        lines.append(f"A级优先（今日共{len(seen)}条，未即时推送的均列于此）：")
        top = seen + rest[:3]
    for i, t in enumerate(top, 1):
        reason = (t.get("angle") or t.get("hook_reason") or "").strip()
        lines.append(f"{i}. [{t.get('rating') or '-'}] {t.get('title', '')} —— {reason[:60]}")
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


def plan_push(state, date_str, fast, trend, degraded, failed, board_path,
              hour=None, breaking_cap=6):
    """生成待推送 [(kind, title, content)] 并原地更新 state。
    kind: breaking/a/daily/alert。"""
    if state.get("date") != date_str:
        carried_pending = state.get("a_pending") or []
        carried_pushed = state.get("pushed") or list(state.get("pushed_a") or [])
        state.clear()
        state.update({"date": date_str, "daily_done": False, "alert_date": "",
                      "a_pending": carried_pending,
                      "pushed": carried_pushed, "a_seen": {}})
    msgs = []
    if "pushed" not in state and state.get("pushed_a"):
        state["pushed"] = list(state["pushed_a"])   # 旧版字段迁移
    pushed = state.setdefault("pushed", [])
    a_seen = state.setdefault("a_seen", {})

    # 1) ⚡突发即时直推（不等评级，B/C 也推；每日安全帽防误报刷屏）
    b_count = state.setdefault("breaking_count", 0)
    for t in fast:
        if t.get("breaking") and t.get("key") not in pushed:
            if b_count >= breaking_cap:
                break
            pushed.append(t.get("key"))
            b_count += 1
            note = (f"（突发信号：{t.get('breaking_hit','铁信号')}"
                    f"，新话题≤{2}h 内命中）")
            msgs.append(("breaking", f"⚡突发 {t.get('title', '')}",
                         _a_digest(t) + "\n" + note))
    state["breaking_count"] = b_count

    # 2) 登记当日 A 级入晚报清单；未推送过的进攒批池
    pending = state.get("a_pending", [])
    for t in fast:
        if t.get("rating") != "A":
            continue
        k = t.get("key")
        a_seen[k] = {"key": k, "title": t.get("title"), "rating": "A",
                     "score": t.get("score", 0), "angle": t.get("angle"),
                     "hook_reason": t.get("hook_reason"), "url": t.get("url"),
                     "track": t.get("track"), "breaking": t.get("breaking", False)}
        if k not in pushed and k not in {p.get("key") for p in pending}:
            item = {"key": k, "title": t.get("title"), "rating": "A",
                    "score": t.get("score", 0), "angle": t.get("angle"),
                    "hook_reason": t.get("hook_reason"), "url": t.get("url"),
                    "track": t.get("track"), "breaking": t.get("breaking", False),
                    "batch_window": None if hour is None else hour // 4}
            pending.append(item)
    state["a_pending"] = [p for p in pending if p.get("key") not in pushed]

    # 3) A 级攒批择优：入池窗口 ≠ 当前窗口的条目才可批推（择优挑最高分 1 条）
    w = None if hour is None else hour // 4
    eligible = [p for p in state["a_pending"]
                if hour is None or p.get("batch_window") != w]
    if eligible:
        best = max(eligible, key=lambda t: t.get("score", 0))
        state["a_pending"].remove(best)
        pushed.append(best.get("key"))
        tag = "⚡突发·" if best.get("breaking") else ""
        msgs.append(("a", f"{tag}A级·本批最优 {best.get('title', '')}",
                     _a_digest(best)))

    # 4) 晚报摘要：21:00 后首轮推（hour=None 兼容立即推）
    if not state["daily_done"] and (hour is None or hour >= 21):
        state["daily_done"] = True
        msgs.append(("daily", f"热点预判晚报 {date_str}",
                     _daily_digest(date_str, fast, trend, board_path, a_seen)))

    # 5) 告警 1 条/天
    if (degraded or failed) and state.get("alert_date") != date_str:
        state["alert_date"] = date_str
        detail = []
        if failed:
            detail.append("失败源：" + ", ".join(failed))
        if degraded:
            detail.append("LLM降级（评级为机械分档）")
        msgs.append(("alert", f"热点预判告警 {date_str}", "\n".join(detail)))
    return msgs
