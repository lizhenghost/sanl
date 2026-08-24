<div align="center">

# 🌊 Sanl

**免费代理节点聚合 · 测速 · 订阅分发一体化平台**

*聚合 15+ 免费节点源 → mihomo 内核真实测速 → 0-100 质量评分 → 一键多格式订阅输出*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/lizhenghost/sanl?include_prereleases&logo=github)](https://github.com/lizhenghost/sanl/releases)
[![CI](https://github.com/lizhenghost/sanl/actions/workflows/ci.yml/badge.svg)](https://github.com/lizhenghost/sanl/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

[功能特性](#-功能特性) · [界面预览](#-界面预览) · [快速开始](#-快速开始) · [订阅输出](#-订阅输出) · [API 文档](#-api) · [常见问题](#-faq)

</div>

---

## ✨ 功能特性

### 🔍 节点聚合
- **多源抓取** — 15+ 预置免费节点源，支持订阅链接 / 粘贴 Base64 / 表单手动导入，12 种协议（SS / SSR / VMess / VLESS / Trojan / Hysteria2 / TUIC / WireGuard…）
- **智能去重** — 按协议+服务器+端口去重，自动补全 GeoIP 国家归属（每 12h 自动更新库）
- **源健康度** — 每源成功率 / 节点数 / 存活率监控，死源自动降权

### ⚡ 真实测速
- **mihomo 内核** — 桥接 [subs-check](https://github.com/xream/subs-check)（Go）做真实协议握手 + 下载测速，拒绝伪测速
- **质量评分** — 延迟 + 下载速度 → 0-100 综合评分，自动分级（优质 / 可用 / 一般 / 较差）
- **定时调度** — 每小时自动抓取 + 测速，测速历史曲线留存 7 天

### 📡 订阅分发
- **四种格式** — Clash YAML / V2Ray Base64 / Sing-box JSON / 混合 Base64
- **Token 鉴权** — 订阅链接 Token 保护，支持创建 / 禁用 / 轮换，记录访问次数与流量统计
- **订阅转换** — 内置转换接口，兼容 NekoBox / OneClick / Shadowrocket 等客户端
- **节点收藏** — 星标节点在所有订阅输出中置顶

### 🛠 运维友好
- **CF 优选** — Cloudflare IP 优选库 + 三网运营商分类 + 网段扫描器
- **边缘中继** — 一键生成 [edgetunnel](https://github.com/zizifn/edgetunnel) Worker 脚本，部署到 CF Workers 做边缘中继
- **可视化** — ECharts 世界地图节点分布 / 延迟分布 / 趋势曲线 / 仪表盘
- **国际化** — 中英双语 + 暗/亮主题 + 移动端自适应（≤768px 底部 Tab）
- **性能** — SQLite WAL 读写并发 + 多级 TTL 缓存 + 线程本地连接池；节点破 5 万可平滑迁 PostgreSQL
- **CI/CD** — 打 tag 自动构建 Release：APK（PWA 打包）/ Windows / 源码包

## 📸 界面预览

| 仪表盘 | 节点列表 |
|:---:|:---:|
| ![仪表盘](docs/screenshots/dashboard.png) | ![节点列表](docs/screenshots/nodes.png) |
| **世界地图** | **暗色主题** |
| ![世界地图](docs/screenshots/worldmap.png) | ![暗色主题](docs/screenshots/dashboard-dark.png) |

## 🚀 快速开始

### Docker（推荐）

```bash
git clone https://github.com/lizhenghost/sanl.git
cd sanl
docker compose up -d --build
```

> 数据持久化在宿主机 `./data`、`./output`、`./config`，删容器不丢数据。
> 需要 HTTPS？取消 `docker-compose.yml` 中 Caddy 注释段并创建 `deploy/Caddyfile`：
>
> ```caddyfile
> your-domain.com {
>     reverse_proxy sanl:8899
> }
> ```

### 本地运行

```bash
pip install -r requirements.txt
python main.py
```

打开 `http://localhost:8899` → 节点源页批量导入预置源 → 测速任务页点「立即测速」→ 订阅输出页拿订阅链接。三步搞定。

## 📡 订阅输出

| 格式 | 端点 | 适配客户端 |
|------|------|-----------|
| Clash YAML | `/api/nodes/subscribe?fmt=clash` | Clash Meta / Stash / ClashX |
| V2Ray Base64 | `/api/nodes/subscribe?fmt=v2ray` | v2rayN / NekoBox / V2Box |
| Sing-box | `/api/nodes/subscribe?fmt=singbox` | Sing-box / SFI / SFA |
| 混合 Base64 | `/api/nodes/subscribe?fmt=base64` | Shadowrocket / Surge |

支持 `limit` / `min_score` / `country` 等筛选参数，详见 API 文档页。

## 📱 安卓 App（PWA）

无需应用商店，手机浏览器访问面板 → 菜单 → **添加到主屏幕**，30 秒装到桌面：

- 独立窗口全屏运行，自动适配刘海屏 / 手势条
- Service Worker 离线缓存，静态资源秒开
- 桌面长按图标直达「立即测速 / 订阅输出」
- 自适应系统深色模式

> 需要 APK？GitHub Actions 已自动构建：到 [Releases](https://github.com/lizhenghost/sanl/releases) 下载 `Sanl-android.apk`。

## ⚙️ 配置

主配置 `config/app.yaml`：

```yaml
server:
  port: 8899
  version: "2.5.1"
scheduler:
  fetch_cron: "0 * * * *"      # 抓取：每小时
  check_cron: "0 * * * *"      # 测速：每小时
  check_mode: speed            # 测速模式：speed / latency / both
```

subs-check 测速参数（并发 / 测速 URL / 合格延迟）在 `config/subs-check.yaml`，首轮运行自动生成。

## 🔌 API

启动后访问 `http://localhost:8899/api/docs` 查看完整交互式 API 文档（OpenAPI）。常用端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/nodes` | 节点列表（筛选 / 分页 / 排序） |
| GET | `/api/nodes/stats` | 节点统计 |
| GET | `/api/nodes/subscribe` | 订阅输出（4 种格式） |
| GET | `/api/ranking` | 评分排名 |
| POST | `/api/check/run` | 手动触发测速 |
| GET | `/api/sources` | 数据源管理 |
| POST | `/api/tokens` | 创建订阅 Token |
| GET | `/api/map` | 世界地图数据 |

## 📖 进阶

<details>
<summary><b>PostgreSQL 迁移（节点数 > 5 万时）</b></summary>

```bash
python3 scripts/migrate_to_pg.py export --sqlite data/nodes.db --out /tmp/export.json
pip install psycopg2-binary
python3 scripts/migrate_to_pg.py import --pg "postgresql://user:pass@host:5432/sanl" --dump /tmp/export.json
```

> SQLite 数据库请放在本地磁盘或 Docker 卷；NFS 网络文件系统存在缓存一致性风险。
</details>

<details>
<summary><b>CF 优选 + 边缘中继</b></summary>

- **CF 优选**：侧边栏「CF 优选」导入优选源，自动按电信 / 联通 / 移动分类，支持网段扫描器自定义扫 IP
- **边缘中继**：CF Worker 页配置节点数 / UUID / 故障转移 IP → 一键生成 `worker.js` → 部署到 Cloudflare Workers
</details>

<details>
<summary><b>目录结构</b></summary>

```
sanl/
├── main.py                 # 主入口
├── config/
│   ├── app.yaml            # 应用配置
│   └── subs-check.yaml     # subs-check 配置（自动生成）
├── presets/
│   └── free_sources.json   # 预置免费源清单
├── src/
│   ├── auth.py             # 认证鉴权
│   ├── schema/             # 数据模型 + SQLite
│   ├── scraper/            # 免费源抓取器
│   ├── checker/            # subs-check 测速引擎
│   ├── scheduler/          # 定时调度
│   └── api/                # FastAPI 路由
├── static/                 # 前端 SPA
├── scripts/                # 构建 / 迁移脚本
└── .github/workflows/      # CI + 自动发布
```
</details>

## 🗺️ Roadmap

- [x] 多源聚合 + 真实测速 + 质量评分
- [x] Token 订阅分发 + 订阅转换
- [x] 世界地图可视化 + PWA
- [x] CF 优选库 + 网段扫描 + edgetunnel 边缘中继
- [x] 多格式导出（CSV / JSON / Clash / Sing-box）
- [ ] 节点可用性推送通知（Telegram / Bark）
- [ ] 多节点池联邦同步

## 🤝 贡献

欢迎 Issue / PR！提交前请跑 `sh regression.sh` 确保全部端点通过。

## ❓ FAQ

<details>
<summary><b>可用节点为什么这么少？</b></summary>
免费源节点存活率天然低（通常 5%-15%），Sanl 的价值在于把真实可用的筛出来。导入更多源 + 提高测速频率可以显著增加可用数量。
</details>

<details>
<summary><b>测速很慢 / 超时？</b></summary>
测速是真实协议握手 + 下载，受上游节点质量影响。可在 <code>config/subs-check.yaml</code> 调低并发或缩短超时。
</details>

<details>
<summary><b>支持 IPv6 吗？</b></summary>
支持。mihomo 内核自动协商，节点侧具备 IPv6 即可。
</details>

## 📄 License

[MIT](LICENSE) © 2026。subs-check (GPL-3.0) 以子进程方式隔离调用，主程序保持 MIT。

## ⚠️ 免责声明

本项目仅供学习、研究和网络诊断技术交流使用，请勿用于非法用途。使用者需遵守所在国家/地区法律法规，因使用本项目产生的任何后果由使用者自行承担。

<div align="center">

**[⭐ Star History](https://star-history.com/#lizhenghost/sanl)**

[![Star History Chart](https://api.star-history.com/svg?repos=lizhenghost/sanl&type=Date)](https://star-history.com/#lizhenghost/sanl)

</div>
