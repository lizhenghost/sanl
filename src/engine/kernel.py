"""mihomo 内核管理器 —— sanl-engine 的数据面。

职责：
- 依据候选节点动态生成 mihomo 配置（N 个 select 组 × N 个 mixed 入站，一一绑定）
- 启动/停止内核子进程，等待外部控制 API 就绪
- 提供通道切换 API（把某通道的出口切到指定节点）

设计说明：真实代理协议栈（ss/vmess/vless/trojan/hysteria2...）由 mihomo 内核承担，
它作为运行时依赖（同 nginx/sqlite 的定位），sanl-engine 的编排/筛选/评分逻辑全部自主实现。
"""
import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# mihomo 明确支持的节点类型白名单（其余类型跳过，防止单个坏节点导致内核启动失败）
SUPPORTED_TYPES = {
    "ss", "ssr", "vmess", "vless", "trojan", "hysteria", "hysteria2",
    "tuic", "snell", "wireguard", "socks5", "http", "mieru", "anytls",
}


class KernelManager:
    """单个 mihomo 实例，多通道（select组×mixed端口）并发探测。"""

    def __init__(self, proxies: List[dict], workdir: str,
                 channels: int = 10,
                 base_port: int = 7891,
                 api_port: int = 9095):
        self.all_proxies = proxies
        self.workdir = Path(workdir)
        self.channels = max(1, channels)
        self.base_port = base_port
        self.api_port = api_port
        self.proc: Optional[subprocess.Popen] = None
        self._group_names = [f"PROBE{i}" for i in range(self.channels)]
        self._ports = [base_port + i for i in range(self.channels)]
        self.api = f"http://127.0.0.1:{api_port}"

    # ---------- 配置生成 ----------

    def _build_config(self) -> dict:
        listeners = []
        groups = []
        for i in range(self.channels):
            listeners.append({
                "name": f"mix{i}",
                "type": "mixed",
                "port": self._ports[i],
                "listen": "127.0.0.1",
                "proxy": self._group_names[i],   # 该入站流量强制走对应 select 组
            })
            groups.append({
                "name": self._group_names[i],
                "type": "select",
                "proxies": [p["name"] for p in self.all_proxies] or ["DIRECT"],
            })
        return {
            "mixed-port": 0,
            "external-controller": f"127.0.0.1:{self.api_port}",
            "mode": "direct",
            "log-level": "warning",
            "ipv6": False,
            "find-process-mode": "off",
            "unified-delay": False,
            "tcp-concurrent": False,
            "profile": {"store-selected": False},
            "listeners": listeners,
            "proxies": self.all_proxies,
            "proxy-groups": groups,
        }

    def _sanitize_proxies(self) -> List[dict]:
        """过滤引擎无法交给内核的节点 + 字段规范化 + 保证名字唯一。
        免费源常见脏数据：vmess cipher 为空/非法（mihomo 会 fatal 拒绝整个配置）、
        缺 uuid/password、port 非数字等。这里尽力修补，修不了的丢弃。"""
        seen = set()
        out = []
        for p in self.all_proxies:
            if not isinstance(p, dict):
                continue
            p = dict(p)  # 不污染调用方
            t = str(p.get("type", "")).lower()
            if t not in SUPPORTED_TYPES:
                continue
            try:
                port = int(p.get("port"))
            except (TypeError, ValueError):
                continue
            server = str(p.get("server") or "").strip()
            if not server or port <= 0 or port > 65535:
                continue
            # ---- 协议字段规范化（防 mihomo fatal） ----
            p["type"] = t
            p["port"] = port
            if t == "vmess":
                cipher = str(p.get("cipher") or "").strip().lower()
                if cipher not in ("auto", "none", "aes-128-gcm", "aes-256-gcm",
                                  "chacha20-poly1305", "chacha20", "aes-128-cfb",
                                  "zero", "aes-256-cfb", "aes-192-cfb"):
                    p["cipher"] = "auto"
                if not str(p.get("uuid") or "").strip():
                    continue
            elif t in ("vless", "tuic") and not str(p.get("uuid") or "").strip():
                continue
            elif t == "trojan" and not str(p.get("password") or "").strip():
                continue
            elif t in ("ss", "ssr"):
                if not str(p.get("cipher") or p.get("security") or "").strip():
                    continue
            elif t == "http":
                # http 代理节点验证：必须至少有一个标识字段非空，否则视为 CF 端点误导入
                if not (p.get("username") or p.get("password") or p.get("uuid")
                        or p.get("cipher")):
                    continue
            name = str(p.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(p)
        return out

    # ---------- 生命周期 ----------

    async def start(self, startup_timeout: float = 25.0) -> None:
        self.workdir = Path(self.workdir).resolve()  # 子进程 cwd 会改相对语义，一律绝对化
        self.workdir.mkdir(parents=True, exist_ok=True)
        proxies = self._sanitize_proxies()
        if not proxies:
            raise RuntimeError("无有效候选节点可交给内核")
        self.all_proxies = proxies

        cfg_path = self.workdir / "probe-config.yaml"
        cfg_path.write_text(
            yaml.safe_dump(self._build_config(), allow_unicode=True, sort_keys=False),
            encoding="utf-8")

        binary = Path(__file__).resolve().parents[2] / "bin" / "mihomo"
        if not binary.exists():
            raise RuntimeError(f"内核二进制缺失: {binary}（运行时依赖，需安装）")

        self.proc = subprocess.Popen(
            [str(binary), "-f", str(cfg_path)],
            stdout=open(self.workdir / "kernel.log", "ab"),
            stderr=subprocess.STDOUT,
            cwd=str(self.workdir),
            start_new_session=True)

        # 等待控制 API 就绪
        deadline = time.monotonic() + startup_timeout
        async with httpx.AsyncClient(timeout=1.5) as c:
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"内核启动即退出 code={self.proc.returncode}"
                                       f"（多为个别节点字段非法，已尽力预校验）")
                try:
                    r = await c.get(f"{self.api}/version")
                    if r.status_code == 200:
                        logger.info(f"[kernel] 就绪: {len(proxies)} 节点 / "
                                    f"{self.channels} 通道 / api:{self.api_port}")
                        return
                except Exception:
                    pass
                await asyncio.sleep(0.4)
        await self.stop()
        raise RuntimeError("内核控制 API 启动超时")

    async def stop(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            await asyncio.wait_for(asyncio.to_thread(self.proc.wait), timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass
        self.proc = None

    # ---------- 通道操作 ----------

    def endpoint(self, channel: int) -> str:
        return f"http://127.0.0.1:{self._ports[channel % self.channels]}"

    async def select(self, channel: int, node_name: str) -> bool:
        """把通道 channel 的出口切到 node_name。"""
        group = self._group_names[channel % self.channels]
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.put(f"{self.api}/proxies/{group}",
                                json={"name": node_name})
                return r.status_code in (200, 204)
        except Exception as e:
            logger.debug(f"[kernel] select 失败 ch={channel} {node_name[:30]}: {e}")
            return False
