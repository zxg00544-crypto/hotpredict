"""prompt 构造：严格 JSON 指令 + 固定系统提示（评级标准与设计 4.3 一致）。"""
import json, re

SYSTEM = (
    "你是一名热点预判员。给你一个热点话题，判断它是否对'社会热点/财经/科技/大咖发言'这四个核心赛道有价值。"
    "只输出一个 JSON 对象，不要任何解释文字。"
    "字段：rating(评级，只能 A/B/C 之一)、track(从给定赛道列表选一个，无则'其他')、"
    "hook_reason(30字内，为什么读者会点)、genre_score(0-10,热点本身的爆款基因)、"
    "fit_score(0-10,与我赛道匹配度)、angle(40字内的写稿角度，A/B 档必填)、"
    "act_now(bool,是否值得1-6小时内动作)、risk(时效/反转风险，低/中/高)。"
    "评级标准：genre_score>=8 且 fit_score>=7 给 A；genre_score>=6 或 fit_score>=8 给 B；"
    "其余给 C。genre 四维看情绪浓度、冲突性、身份相关、意外度。"
)

def pick_track(title: str, tracks: dict) -> str:
    t = title.lower()
    for track, words in (tracks or {}).items():
        for w in words:
            wl = w.lower()
            if wl.isascii() and wl.isalnum():
                if re.search(r"(?<![a-z0-9])" + re.escape(wl) + r"(?![a-z0-9])", t):
                    return track
            elif wl in t:
                return track
    return "其他"

def build_pack(topic: dict, age_label: str) -> dict:
    return {
        "title": topic.get("title", ""),
        "bucket": age_label,
        "sources": topic.get("sources", []),
        "score": topic.get("score", 0),
        "growth_G": topic.get("G", 0),
        "heat": topic.get("heat", 0),
        "age_hours": topic.get("age_hours", 0),
        "url": topic.get("url", ""),
        "reason": topic.get("reason", ""),
        "tracks": list((topic.get("tracks") or {}).keys()),
    }

def build_messages(pack: dict) -> list:
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                "可选赛道：" + json.dumps(pack.get("tracks") or ["科技"], ensure_ascii=False) + "\n"
                "话题数据：" + json.dumps(pack, ensure_ascii=False)}]
