# Sanl Changelog

## v2.5.1 - 2026-08-24

### 🔧 CI 修复
- 修复 GitHub Actions `permissions` 缺失导致 Release 上传失败
- 补装 `python-multipart` 依赖，4 个 workflow 全绿
- Android APK（3.1MB）正式附带 Release 下载

### 🎨 前端
- 表格列显隐浮层重构（修复 `details` containment 导致的弹层裁剪）

## v2.5.0 - 2026-08-23

### ⚙️ 稳定性与性能
- 健康检查增强：死源自动降权 + 存活率统计
- 缓存层增强：TTL 命中率浮标实时展示
- SQLite 查询优化：高频接口索引覆盖
- 修复文件句柄泄漏（subs-check 子进程日志流）

### 📱 安卓
- GitHub Actions 自动构建 debug APK 并上传 Artifact

## v2.4.3 - 2026-08-23

### 📱 安卓
- 新增 `android-build.yml`：PWA → TWA 打包 APK，Release 附 `Sanl-android.apk`

## v2.4.2 - 2026-08-23

### 🚀 边缘中继
- 集成 [edgetunnel](https://github.com/zizifn/edgetunnel)：`POST /api/edgetunnel/generate` 从节点池取优质 vless/vmess+ws 节点，生成可部署到 CF Workers 的中继脚本
- 前端新增 **🚀 CF Worker** Tab：配置节点数/UUID/故障转移 IP，一键生成、复制/下载 `worker.js`
- 清理 5 个冗余 TODO 文档；修复 `static/index.html` ↔ `frontend/index.html` 循环软链接

## v2.4.1 - 2026-08-23

### 🔧 引擎修复
- 活跃节点 12 → 44：importer 域名型解析 + 字段规范化 + 并发标定 + cfconvert 双 Tab
- TLS 预检查过滤死节点（72.5% 通过），6 个探测端点覆盖国内外可达性
- 修复订阅转换后端异常：Clash YAML 注释断行 + inline 缩进保留 + 单协议导出兼容 NekoBox/OneClick
- 修复 Token 500（缺 traffic_limit_mb）+ 真分页 + Clash groups/rules + 趋势图全 0 + 流媒体检测 + 国旗/地图渲染
- 新增源级测速开关 / max_sources / 续期天数

## v2.4.0 - 2026-08-22

### ⚡ 测速维度可选（本次核心）
- `POST /api/check/run` 新增 `mode` 参数: `latency`(仅延迟) / `speed`(延迟+速度) / `full`(全量含流媒体)
- 新增 `overrides` JSON body 白名单覆盖: concurrent/timeout/min-speed/download-mb/download-timeout/speed-concurrent 等
- 前端测速页新增模式三选卡与高级参数面板；进度条显示当前模式徽章
- 定时测速默认模式可配: `scheduler.check_mode`（默认 speed）

### 🚀 测速提速
- 结果文件等待从固定 60s 改为动态稳定检测(~15s)，轮询间隔 5s→3s
- latency 模式跳过流媒体检测/IP 重命名/速度下载三大耗时项，**实测 97 秒完成 21362 节点全流程**

### 🏷️ 品牌更名
- 全项目 NodePool → **Sanl**：前端标题/logo、API 文档、日志、User-Agent、构建脚本、CI Release、docker-compose、README/CONTRIBUTING/STATUS

### 📱 安卓 App (PWA)
- Web App Manifest + Service Worker（根 scope，API 网络优先、静态离线缓存）
- 应用图标(192/512 + maskable)、主题色、桌面快捷方式（立即测速/订阅输出）
- README 新增安卓/iOS 安装指南与 TWA 打包 APK 说明
## v2.0.0 - 2026-08-21

### 🚀 Phase 2 新功能
- **Token 鉴权系统** — 订阅链接 Token 保护（np_ 前缀 64 位 hex），支持创建/禁用/删除，`Authorization: Bearer` / `X-API-Key` / URL 参数三种传递方式
- **多用户系统** — 用户注册/登录（SHA-256+salt 密码哈希），admin/user 角色权限，会话 token
- **世界地图可视化** — ECharts 世界地图 + 节点散点分布 + 各国节点统计柱状图（`GET /api/map`）
- **数据源管理面板** — 15 个预置免费节点源批量导入、Base64 粘贴导入、源健康度监控
- **自动 GitHub Release** — GitHub Actions workflow + 本地打包脚本（tar.gz/zip）

### 🔧 优化
- 前端升级为 8 页面单页应用（仪表盘/节点/地图/数据源/测速/订阅/Token/用户）
- 修复 schema.sql 中 latency/download_speed 列重复定义
- 订阅输出页面支持格式/数量/最低评分参数化生成链接

### 🐛 修复
- 修复前端 index.html 文件截断导致的 JS 语法错误
- 修复世界地图 GeoJSON 未注册问题（动态加载 CDN world.json）

## v1.0.0 - 2026-08-20

### Phase 1 MVP
- FastAPI 后端 + SQLite + APScheduler 定时调度
- subs-check 测速引擎桥接（子进程调用）
- 免费节点源抓取与去重合并
- 节点质量评分与排名（0-100 分）
- Clash 订阅输出
- Web 仪表盘（ECharts 图表）
- nginx 反向代理 + Cloudflare Tunnel 公网访问
