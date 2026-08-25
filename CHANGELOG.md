# 更新日志 / Changelog

所有显著变更都会记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

- （进行中的改动见 [commits](https://github.com/lizhenghost/sanl/commits/main)）

## [v2.6.0] — 2026-08-25

### 🎨 前端面板四大模块重构（信息架构升级）

- **导航重组为四大模块**：
  - 📊 **仪表盘** —— 总览、趋势、排名、地图入口
  - 🧩 **节点池** —— 节点列表 / 世界地图 / 来源管理 / 测速任务 / ☁️ CF 优选（所有优选节点相关功能归位节点池）
  - 🔄 **订阅转换** —— 订阅转换 / 订阅输出 / 令牌管理
  - 🛠 **开发者工具** —— CF Worker / 💻 系统状态（新增）/ API 文档
- **去重**：修复侧边栏「CF Worker」重复出现两次的问题；「文档」独立组并入开发者工具
- **新增模块内子导航条**（pill tabs）：桌面/移动统一，粘性悬浮、渐变高亮，移动端横向滚动切换
- **移动端底部 Tab 精简**：6 个入口 → 4 大模块（仪表盘/节点池/订阅转换/开发者），模块内靠子导航条切换
- **新增 💻 系统状态页**：版本 / 运行时长 / 数据库健康 / 节点总数 / 缓存命中率 / 后台任务一览
- i18n 字典随新架构重构（中/英即时切换含子导航）
- Playwright 实测：桌面 1440px + 移动 390px 双端零 JS 报错，截图验证通过

## [v2.5.4] — 2026-08-25

### ☁️ CF 优选中心三合一（重大功能）

- **理念修正**：优选 IP 不再只是"加速素材"——新增一键转节点能力，可直接连接使用
- 新增 `src/engine/cf_hub.py` 核心引擎：
  - `harvest_domains`：批量解析大佬优选域名 → 域名背后全部任播 IP 自动入端点库（一个域名常含几十个 IP，全收）
  - `find_cf_templates`：自动发现节点池中走 CF CDN 中转的模板节点（vless/vmess + ws + tls，按 uuid+Host+path 分组去重）
  - `endpoints_to_nodes`：延迟最优端点 × 模板 → 节点变体（server=优选IP，Host/SNI=原机场域名）指纹去重入池
- 新增 API：`GET /api/cf/hub`（一屏总览）、`POST /api/cf/harvest`（域名解析入库）、`POST /api/cf/to-nodes`（⭐ 一键转节点）
- **前端合并**：「CF 优选中心」单页三区块流程 —— ①来源解析入库 → ②统一检测+端点池 → ③⭐转节点入池；网段扫描收进页内「高级」折叠入口，CF 相关导航页 3 → 2
- 转出的变体节点与其他节点一起参加统一测速排名，可订阅、可直连
- 实测数据：18 组模板 / 单次转换 30 变体 / 全量 TCPing 43,200 端点测活 73% 最优 2ms

### 🐛 修复

- GeoIP 补全失效：`list_nodes_missing_geo` 查询条件漏掉 country_code 为空的节点，导致历史节点国家码永不补全；修复后 active 节点 country_code 覆盖率 10% → **100%**
- 新增 `GET /api/nodes/{id}` 节点详情端点（含 node_data 原始配置）

## [v2.5.3] — 2026-08-25

- 刷新 CF IP 段缓存（例行运行时数据）
- 包含 v2.5.2 之后累积的跨平台适配与 GeoIP 修复

## [v2.5.2] — 2026-08-24

### ✨ 功能

- 源发现（discover）随机化 + 高星仓库优先排序

### 🐛 修复

- 安卓端适配修复
- subs-check 内核文件句柄泄漏修复
- 抓取器连接池坏死自愈 + 错误日志带异常类型

### 📝 文档

- README 按 GitHub 高星项目规范重写（徽章/截图/FAQ/免责声明）
- 补充 v2.4.1–v2.5.1 changelog 与 issue templates

## [v2.5.1] — 2026-08-23

### 🐛 修复

- CI workflow permissions 缺失导致 Release 上传失败（Resource not accessible by integration）
- python-multipart 依赖缺失导致源导入接口 500
- 列显隐浮层重构（修复 details/containment 层级问题）
- APK 构建并附上 Release（3.1MB debug 签名可直接安装）

## [v2.5.0] — 2026-08-22

### ⚡ 稳定性巡检（每日巡检机制首轮产出）

- 健康检查增强
- 后端缓存层增强
- SQLite 查询优化
- 文件句柄泄漏修复
- 12/12 回归通过

## [v2.4.3] — 2026-08-21

- feat(android): APK 构建流水线 + 自动上传 GitHub Release

## [v2.4.2] — 2026-08-20

### ✨ 功能

- **edgetunnel 集成**：`POST /api/edgetunnel/generate` 从节点池取优质节点生成可部署到 Cloudflare Workers 的 JS 边缘中继脚本；前端新增 🚀 CF Worker Tab，一键生成/复制/下载 worker.js
- 本地测速选优 + CF 边缘快速中继互补架构

### 🧹 清理

- 移除 5 个冗余 TODO 文件
- 修复 static/index.html ↔ frontend/index.html 循环软链接

## [v2.4.1] — 2026-08-19

### 🐛 修复（活跃节点数专项）

- 活跃节点从 12 提升至 44+：importer 域名型 server 解析 + 字段规范化 + 并发超时标定
- 节点状态机修复：unknown 状态永不降级导致 7417 个死节点统计失真
- Token 接口 500（缺 traffic_limit_mb 字段）+ 真分页 + Clash 完整配置补全

### ✨ 功能 / 性能

- 后端 TTL 缓存层 + 前端缓存命中率浮标 + 自适应轮询节流
- 测速并发提升：concurrent 120→240 / speed-concurrent 40→100
- SPA 路由 fallback + PWA 更新机制 + node_data JSON 容错

## [v2.4.0] — 2026-08-18

### ✨ 功能

- **测速维度可选**（latency/speed/full）+ 参数覆盖，测速提速至 97s 实测
- **品牌更名 Sanl**
- **安卓 PWA App**
- 全局任务进度条系统（抓取/测速后台任务统一视图，前端悬浮进度条 2.5s 轮询）
- 抓取频率改每小时整点 + 死源自动清理（fail≥5 自动禁用 24h）
- 源健康度判定反转 bug 修复 + API 文档本地化（去 jsdelivr CDN 依赖）
- 方案 v2.1 大纲 12 项功能实证落地

## [v2.3.0] — 2026-08-17

- 十项优化合集
- 扫描崩溃修复
- 全源测速 + 合格延迟可调（`POST /api/admin/apply-qualified-latency`）

## [v2.2.3] — 2026-08-16

- fix: 表格列被裁切不可滑——table-container 全局 overflow-x:auto + table min-width 兜底

## [v2.2.2] — 2026-08-16

- fix: GeoIP 域名出口识别失效
- fix: 节点列表排序接口 500

## [v2.2.1] — 2026-08-15

- refactor: 前端信息架构重构 + 版本号链路修复

## [v2.2.0] — 2026-08-14

### ✨ 功能（平台成型）

- **订阅转换功能上线**——平台正式分为两大模块（节点池聚合 + 订阅中心）
- **测速实时进度系统**——前台(手动)/后台(定时)双模式
- **CF 网段扫描器**（参考 CFData-WEB v1.7.8）：官方/非标优选 + 端口可选 + 并发控制 + 合格阈值 + TOP-N + Host 伪装下载测速 + cachefly 等 5 个测速网址 + /24 精简采样
- **接入 bestcf + 090227 全部优选订阅**（32 新源，cf-list 共 45）+ CF 端点 TCP 延迟检测引擎
- **CF 优选按运营商分类**（电信/移动/联通/三网）：isp 列 + 自动识别 + API 筛选 + 导出
- 节点池导入架构重构：全源解析入库 + 指纹去重 + 测速不删库 + 10 格式导出
- 白蓝主题 UI 重构 + 网络工具去重
- CF 端点 IPv4/IPv6 分类（v6 方括号解析修复）
- 测速定时改每 4 小时（0/4/8/12/16/20 点）

### 🐛 修复

- 前端异步加载器跨页竞态空指针崩溃
- nginx 强制 HTTPS 跳转

## [v2.1.0] — 2026-08-13

- 首个正式发布 tag
- 推送前清理：移除 GPL 二进制与会话 TODO 笔记
