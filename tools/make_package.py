# -*- coding: utf-8 -*-
"""热点预判 换电脑双版本打包器（设计 docs/2026-09-29-项目打包-design.md）。

用法: python -X utf8 tools/make_package.py [YYYYMMDD]
只读源目录，只写 打包\\。真实密钥零进包：模板脱敏 + 成品扫描双保险。
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import zipfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "打包")

# 设计红线：config.yaml 须脱敏的 6 键
CONFIG_SECRET_KEYS = {
    "weibo_cookie": "微博cookie",
    "api_key": "LLM api_key",
    "serverchan_sendkey": "Server酱sendkey",
    "dingtalk_webhook": "钉钉webhook",
    "dingtalk_secret": "钉钉secret",
    "dingtalk_keyword": "钉钉keyword",
}
SECRETS_JSON_KEYS = {
    "SecretId": "腾讯云SecretId",
    "SecretKey": "腾讯云SecretKey",
}

DIRS_COMMON = ["collectors", "scoring", "llm_judge", "render", "tests", "docs"]
DIRS_LOCAL = ["日报", "看板", "states"]
DIRS_CLOUD = ["deploy"]
FILES_COMMON = [
    "main.py", "db.py", "scf_handler.py", "probe.py", "probe_llm.py",
    ".gitignore",
    "requirements.txt", "修订交接文档.md",
]
EXCLUDE_NAMES = {"__pycache__", "build", "fn.zip"}
EXCLUDE_FILES = {"config.yaml", "secrets_tencent.json"}


def sanitize_yaml(text: str) -> str:
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if ":" in stripped:
            key, _, _val = stripped.partition(":")
            key = key.strip().strip("\"'")
            if key in CONFIG_SECRET_KEYS:
                out.append("%s%s: <填写:%s>" % (indent, key, CONFIG_SECRET_KEYS[key]))
                continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def sanitize_secrets_json(text: str) -> str:
    data = json.loads(text)
    for k, label in SECRETS_JSON_KEYS.items():
        if k in data:
            data[k] = "<填写:%s>" % label
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _iter_files(version: str):
    assert version in ("local", "cloud"), version
    dirs = list(DIRS_COMMON) + (DIRS_LOCAL if version == "local" else DIRS_CLOUD)
    for name in FILES_COMMON:
        yield name
    yield "README-本地版.md" if version == "local" else "README-云端版.md"
    for d in dirs:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = [x for x in dns if x not in EXCLUDE_NAMES]
            rel = os.path.relpath(dp, ROOT).replace("\\", "/")
            for fn in sorted(fns):
                if fn.endswith(".pyc") or fn in EXCLUDE_FILES or fn in EXCLUDE_NAMES:
                    continue
                yield (rel + "/" + fn).replace("//", "/")
    if version == "local":
        yield "热点.db"
        yield "install_schedule.ps1"
        yield "run_once.ps1"


def make_templates(dst: str) -> None:
    cfg = open(os.path.join(ROOT, "config.yaml"), encoding="utf-8").read()
    with open(os.path.join(dst, "config.example.yaml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sanitize_yaml(cfg))
    sec = open(os.path.join(ROOT, "secrets_tencent.json"), encoding="utf-8").read()
    with open(os.path.join(dst, "secrets_tencent.example.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sanitize_secrets_json(sec))


def real_secret_values() -> list:
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
    vals = [cfg.get("weibo_cookie"), (cfg.get("llm") or {}).get("api_key")]
    notify = cfg.get("notify") or {}
    for k in ("serverchan_sendkey", "dingtalk_webhook", "dingtalk_secret", "dingtalk_keyword"):
        vals.append(notify.get(k))
    sec = json.load(open(os.path.join(ROOT, "secrets_tencent.json"), encoding="utf-8"))
    vals.extend([sec.get("SecretId"), sec.get("SecretKey")])
    return [str(v) for v in vals if v and len(str(v)) >= 8]


def secret_scan(staged_root: str, real_values=None) -> list:
    if real_values is None:
        real_values = real_secret_values()
    hits = []
    for dp, dns, fns in os.walk(staged_root):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, staged_root).replace("\\", "/")
            try:
                body = open(full, "r", encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for val in real_values:
                if val in body:
                    hits.append(rel)
                    break
    return hits


def build(version: str, date: str) -> str:
    label = "本地版" if version == "local" else "云端版"
    zip_path = os.path.join(OUT_DIR, "热点预判-%s-%s.zip" % (label, date))
    stage = tempfile.mkdtemp(prefix="hotpredict_pkg_")
    try:
        staged_root = os.path.join(stage, "热点预判")
        os.makedirs(staged_root, exist_ok=True)
        for rel in _iter_files(version):
            src = os.path.join(ROOT, rel.replace("/", os.sep))
            dst = os.path.join(staged_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        make_templates(staged_root)
        hits = secret_scan(staged_root)
        if hits:
            raise SystemExit("密钥泄漏，拒绝组包: %s" % hits)  # 只打路径与键位，不打值
        os.makedirs(OUT_DIR, exist_ok=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, _dns, fns in os.walk(staged_root):
                for fn in sorted(fns):
                    full = os.path.join(dp, fn)
                    arc = "热点预判/" + os.path.relpath(full, staged_root).replace("\\", "/")
                    z.write(full, arc)
        return zip_path
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().strftime("%Y%m%d")
    for version in ("local", "cloud"):
        path = build(version, date)
        with zipfile.ZipFile(path) as z:
            n = len(z.namelist())
        print("created %s (%d files, %.1f KB)" % (path, n, os.path.getsize(path) / 1024))
    print("secret scan: clean (0 hits, values never printed)")


if __name__ == "__main__":
    main()
