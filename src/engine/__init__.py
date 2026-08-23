"""sanl-engine —— 自主研发的节点测速筛选引擎（纯 Python 编排层）。

设计要点（自主创新，未搬运任何外部项目代码）：
- 三级漏斗管线：L1 TCP 测活（纯 asyncio）→ L2 真实代理链路探测 → L3 经代理下载测速。
  万级节点先在 L1 用毫秒级 TCP 握手筛掉绝大多数死节点，昂贵的 L2/L3 只花在候选上。
- 数据面通过本机 mihomo 内核（bin/ 下运行时依赖，如同 nginx/sqlite）转发真实流量；
  编排、解析、去重、评分、命名、输出全部为本项目自主实现。
- 输出兼容 Clash proxies 列表，节点名含 延迟|速度 指标，直接对接既有回填管道
  （顺带根治历史 latency=NULL 问题——subs-check 命名模板不含延迟）。

模块：
- models    : 引擎数据结构（Candidate / ProbeOutcome）
- fetcher   : 订阅并发拉取器
- tcplayer  : L1 TCP 批量测活
- kernel    : mihomo 内核生命周期与多通道管理
- prober    : L2/L3 探测器（经内核 mixed 端口）
- namer     : 节点命名模板（国旗|延迟|速度）
- pipeline  : 管线编排入口 run_pipeline()
"""
from .pipeline import run_pipeline  # noqa: F401
