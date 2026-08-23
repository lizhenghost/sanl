"""节点命名模板：国旗 + 国家码_序号 | 延迟 | 速度。

格式 `{flag}{CC}_{i}|{latency}ms|{speed}` 与既有回填解析
（checker._parse_and_store_results 按 | 分段提取 emoji/KB/s/ms）完全兼容，
延迟与速度自此直接入库，根治历史 latency=NULL 问题。
"""
import re
from typing import List, Optional

from .models import Candidate

# 节点名里常见国旗 emoji → 提取两位国家码（unicode 区域指示符）
_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
# 名称中的 ISO 国家码片段，如 "US", "JP-01", "[HK]"
_CC_RE = re.compile(r"\b([A-Z]{2})\b")


def flag_of(country_code: str) -> str:
    """两位国家码 → 国旗 emoji（区域指示符偏移计算）。未知返回空串。"""
    cc = (country_code or "").strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return chr(0x1F1E6 + ord(cc[0]) - ord("A")) + chr(0x1F1E6 + ord(cc[1]) - ord("A"))


def code_from_flag(flag: str) -> str:
    if len(flag) == 2 and all(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in flag):
        return "".join(chr(ord("A") + ord(ch) - 0x1F1E6) for ch in flag)
    return ""


def guess_country(cand: Candidate) -> str:
    """从候选节点现有信息猜两位国家码：优先引擎 GeoIP 结果，其次原名 emoji/文本。"""
    cc = getattr(cand, "country_code", "") or ""
    if len(cc) == 2:
        return cc.upper()
    m = _FLAG_RE.search(cand.name)
    if m:
        return code_from_flag(m.group(0))
    m = _CC_RE.search(cand.name.upper())
    if m:
        return m.group(1)
    return ""


def rename_alive(alive: List[Candidate]) -> list:
    """对存活候选生成最终 clash proxies 列表（含新名字与实测指标）。

    命名：{flag}{CC}_{序号}|{延迟}ms|{速度KB/s}   （速度缺失则该段省略）
    """
    counter: dict = {}
    out = []
    for c in alive:
        cc = guess_country(c)
        flag = flag_of(cc) or "❓"
        key = cc or "XX"
        counter[key] = counter.get(key, 0) + 1
        parts = [f"{flag}{key}_{counter[key]}"]
        if c.latency is not None:
            parts.append(f"{int(c.latency)}ms")
        if c.download_speed:
            kbs = c.download_speed / 1024.0
            parts.append(f"{kbs:.0f}KB/s")
        name = "|".join(parts)

        proxy = dict(c.proxy)
        proxy["name"] = name
        out.append(proxy)
    # 全局按延迟排序输出（低延迟在前）
    return out
