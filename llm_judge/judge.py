"""LLM 评级 + 资格校验 + 失败降级。调用走 probe_llm.llm_client_call，禁止另写 HTTP。"""
import json, re
from probe_llm import llm_client_call
from llm_judge.prompt import build_messages

VALID = {"A", "B", "C"}

def parse_rating(text: str):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    rating = str(obj.get("rating", "")).strip().upper()
    if rating not in VALID:
        return None
    obj["rating"] = rating
    try:
        obj["genre_score"] = int(obj.get("genre_score", 0))
        obj["fit_score"] = int(obj.get("fit_score", 0))
    except (TypeError, ValueError):
        return None
    return obj

def judge_topic(pack: dict, cfg: dict):
    res = llm_client_call(build_messages(pack), cfg)
    if not res:
        return None
    obj = parse_rating(res.get("content"))
    if obj is None:
        return None
    obj["model"] = res.get("model", "")
    return obj
