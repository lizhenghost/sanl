# Sanl 节点池平台 — 运行实况

> 最后更新：2026-08-28 13:15 CST | 版本 **v2.6.0**

## 服务状态

| 检查项 | 状态 |
|--------|------|
| 公网 HTTPS | ✅ https://lzsanlzhuanhuan.kdns.fr/（Cloudflare Tunnel） |
| 本地 HTTP | ✅ http://127.0.0.1:8899/ |
| 进程保活 | ✅ 后台 keepalive 循环（cloudflared + python3 main.py + port-forward） |
| GitHub CI | ✅ v2.6.0 — CI / Android APK / Windows EXE / Build & Release 全绿 |

## 节点池状态

| 指标 | 数值 |
|------|------|
| 总节点数 | 37 |
| active（有延迟且<800ms） | 14 |
| inactive（有延迟但>800ms） | 8 |
| 数据库大小 | ~14 KB（极简，无僵尸冗余） |
| 活跃国家 | 🇺🇸 US(6) / 🇿🇦 ZA(2) / 🇩🇪 DE(2) / 🇯🇵 JP(1) / 🇬🇧 GB(1) / 🇫🇷 FR(1) / 🇷🇺 RU(1) |

> 注：本池来源于 GitHub 公开订阅，节点数量少属正常（大部分机场节点已关停或限速）。
> 如需更多节点，可粘贴更多订阅 URL 到「📥 来源导入」自动抓取。

## v2.6.0 修复清单

1. **🐛 delay 估算**：subs-check speed 模式名称格式为 `国家|速度`，无延迟；
   改为从下载速度反推（`latency = max(50, 2048000/download_speed_bytes)`），消除 98% 节点 latency=NULL。
2. **🐛 qualified_latency 纳入 NULL**：`apply_qualified_latency(800)` 同步检查 `latency IS NULL`，
   清除假 active 节点。
3. **🛡️ 安全**：debug=false，api_key 改为随机值（非默认 `changeme`）。
4. **🛡️ gaierror 防护**：8 处 `asyncio.gather()` 加 `return_exceptions=True`（cf_ping/cf_scanner/cf_hub/fetcher/prober/tcplayer/geoip/converter）。
5. **🧹 数据库清理**：删除 11,670 个 inactive 僵尸节点，DB 从 14.5 MB → 极小。
6. **📦 版本**：2.5.2 → 2.6.0。

## 关键路由

| 路由 | 说明 |
|------|------|
| `GET /api/version` | 版本与配置 |
| `GET /api/nodes/stats` | 节点统计 |
| `GET /api/nodes` | 节点列表（支持筛选/排序/分页） |
| `GET /api/cf/hub` | CF 优选中心概览 |
| `POST /api/cf/harvest` | 解析优选域名入库 |
| `POST /api/cf/to-nodes` | 优质端点⭐→节点变体入池 |
| `GET /api/tasks` | 后台任务状态 |
| `GET /api/sources/health` | 来源源健康检查 |

## v2.6.1 修复——ClastMate 导入报错

**现象**：Android ClashMate 导入订阅时报 `yaml: unmarshal errors: line 1: cannot unmarshal !!str 'hysteri...' into config.RawConfig`

**根因**：subs-check 存库的节点包含 hysteria/hysteria2/tuic 协议，
但 Clash 基础版（非 Meta）不支持这些协议，生成 YAML 后 ClashMate 解析失败。

**修复**：
1. `src/api/subscribe.py::generate_clash()` 跳过 `hysteria/hysteria2/tuic` 节点
2. `src/api/converter.py::convert_text()` 检测空导出并返回明确错误
3. 订阅端点 `/api/nodes/subscribe?format=clash` 自动过滤

**验证**：
- `hysteria2 → clash` → `ok=False`，错误信息明确
- `hysteria2 → clash-meta` → `ok=True`，正常导出
- `ss + hysteria2 → clash` → `ok=True`，仅导出 ss 节点
