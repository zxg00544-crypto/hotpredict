"""LLM 探针与 OpenAI 兼容调用。key 只在内存里，不写日志不落盘。"""
import json, sys, requests
import yaml

def load_cfg(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_llm_cfg(cfg: dict) -> dict:
    with open(cfg["llm"]["config_path"], encoding="utf-8") as f:
        prov = json.load(f)["provider"][cfg["llm"]["provider"]]
    return {"base_url": prov["options"]["baseURL"].rstrip("/"),
            "api_key": prov["options"]["apiKey"],
            "model": cfg["llm"]["model"],
            "fallback_models": cfg["llm"].get("fallback_models") or [],
            "timeout_topic": cfg["llm"].get("timeout_topic", 15),
            "retries": cfg["llm"].get("retries", 2)}

def pick_model(llm: dict) -> list:
    return [llm["model"]] + list(llm.get("fallback_models") or [])

def chat(messages, llm_cfg, model, json_mode=True):
    body = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(llm_cfg["base_url"] + "/chat/completions",
                      headers={"Authorization": "Bearer " + llm_cfg["api_key"],
                               "Content-Type": "application/json"},
                      json=body, timeout=llm_cfg["timeout_topic"])
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def llm_client_call(messages, cfg, json_mode=True):
    """按备选链依次尝试；返回 {'content':str,'model':str} 或 None。"""
    try:
        llm = load_llm_cfg(cfg)
    except Exception:
        return None
    for model in pick_model(llm):
        for _ in range(llm["retries"] + 1):
            try:
                return {"content": chat(messages, llm, model, json_mode), "model": model}
            except Exception:
                continue
    return None

if __name__ == "__main__":
    cfg = load_cfg(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    res = llm_client_call([{"role": "user",
                            "content": "只输出JSON：{\"ok\": true}"}], cfg)
    if res is None:
        print("LLM PROBE FAIL all models exhausted")
        sys.exit(1)
    try:
        json.loads(res["content"])
        print("LLM PROBE PASS model=" + res["model"])
    except Exception as e:
        print("LLM PROBE FAIL json: " + str(e))
        sys.exit(1)
