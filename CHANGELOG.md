# NodePool Changelog

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
