"""引擎数据结构。"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class Candidate:
    """待测节点（clash proxies 字典 + 引擎附加字段）"""
    proxy: Dict[str, Any]          # clash 格式节点（name/type/server/port/...）
    fingerprint: str = ""          # 去重指纹
    tcp_rtt: Optional[float] = None    # L1 TCP 握手 RTT ms
    latency: Optional[int] = None      # L2 应用层延迟 ms（经代理 HTTP）
    download_speed: Optional[int] = None  # L3 下载速度 B/s
    country: str = ""                  # 国旗 emoji（GeoIP/节点名提取）
    alive: bool = False

    @property
    def name(self) -> str:
        return str(self.proxy.get("name", ""))


@dataclass
class StageStats:
    """各阶段统计（供进度面板与结果汇总）"""
    fetched_sources: int = 0
    parsed_nodes: int = 0
    deduped_nodes: int = 0
    l1_alive: int = 0
    l15_alive: int = 0
    l2_alive: int = 0
    l3_passed: int = 0

    def as_dict(self) -> Dict[str, int]:
        return dict(
            fetched_sources=self.fetched_sources,
            parsed_nodes=self.parsed_nodes,
            deduped_nodes=self.deduped_nodes,
            l1_alive=self.l1_alive,
            l15_alive=self.l15_alive,
            l2_alive=self.l2_alive,
            l3_passed=self.l3_passed,
        )


@dataclass
class EngineResult:
    """一轮引擎运行的最终产出"""
    ok: bool = True
    error: str = ""
    stats: StageStats = field(default_factory=StageStats)
    alive_proxies: List[Dict[str, Any]] = field(default_factory=list)  # 命名后的 clash proxies
    elapsed: float = 0.0
