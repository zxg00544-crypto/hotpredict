"""Signal 数据契约、topic_key 归一化、Collector 协议。全项目唯一口径。"""
import re, hashlib
from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class Signal:
    topic_key: str
    source: str
    title: str
    url: str
    heat: float
    rank: int
    rank_delta: int
    engagement: float
    author_weight: float
    published_at: str = ""
    fetched_at: str = ""
    raw: dict = field(default_factory=dict)

def topic_key(title: str) -> str:
    """归一化标题做聚合键：去空白/标点、小写；短则可读，长则截断+hash。"""
    norm = re.sub(r"[\s\W_]+", "", title or "", flags=re.UNICODE).lower()
    if not norm:
        return "empty"
    if len(norm) <= 48:
        return norm
    return norm[:32] + hashlib.md5(norm.encode("utf-8")).hexdigest()[:8]

class Collector(Protocol):
    name: str
    def fetch(self, cfg: dict) -> list: ...
