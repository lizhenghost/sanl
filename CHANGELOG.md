# Sanl Changelog


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
