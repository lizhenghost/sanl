# NodePool 运行态快照 — v2.3.1 (97af632, 已推GitHub)

## 方案v2.1最终对照补全 (2026-08-22)
对照初始大纲 node-pool-platform-proposal-v2.md 逐项 grep 实测,12项缺口落地:
GitHub仓库自动发现/RSS解析/文件上传导入/订阅分类/自动黑名单(fail≥3→dead)/手动封禁/
effectScatter热点/Token流量限额(429)/流媒体解锁media-check/API文档入口/config.example.yaml/NodeStatus枚举。
如实预留: RBAC三级角色、WS实时进度。回归15/15+新功能8/8全过

**更新**: 2026-08-22 | 后端 PID 见 pgrep -f main.py | http://127.0.0.1:8899

## v2.3.0 十项优化（全部完成）
1. GeoIP 自动刷新（12h 定时 + 每轮测速后）✅
2. 节点收藏夹 ⭐（星标→订阅置顶）✅
3. 订阅分发统计（token 维度 hits/流量/UA，令牌页卡片）✅
4. 健康历史曲线 📈（每轮测速快照 node_health_history，列表弹层双轴图）✅
5. CSV/JSON 导出（可选含延迟列）+ 表格列显隐 ✅
6. 移动端底部 Tab（≤768px 五宫格，侧边栏隐藏）✅
7. 暗/亮主题 🌙 + 中英 i18n EN ✅
8. SQLite WAL+busy_timeout（NFS 自动降级）+ scripts/migrate_to_pg.py ✅
9. Docker Compose 完善（healthcheck/log rotate/Caddy 注释段）+ README 部署章节 ✅
10. i18n 框架层（导航/分组/底部Tab/页标题）✅

## 本轮修复与新增
- fix: CF 扫描 `_tcping is not defined` 崩溃（cf_scanner.py 别名不一致）→ 实测扫描 120/120 完成
- fix: importer.py ipaddress 未导入 NameError
- feat: 手动导入节点经 `/sub/internal/manual` 参与每轮测速（manual_count>0 时自动加入 sub-urls）
- feat: 合格延迟阈值默认 200ms（config/app.yaml scheduler.qualified_latency_ms）
  - 测速任务页「🎯 合格判定」卡可改 + 立即重判（POST /api/admin/apply-qualified-latency）
  - 每轮测速后自动把 latency>阈值 的 active 节点标 inactive
- feat: 测速网址 +5 国内镜像（阿里云/清华/中科大/腾讯/华为），下拉共 12 项
- feat: CF 扫描写导出 txt 可选「附带延迟」（ip:port#延迟ms 格式）
- feat: 自动测速间隔改为每小时整点（check_cron "0 * * * *"）

## 验证状态
- Playwright 回归 21/21 通过（15 主回归 + 6 新 UI 检查）
- API 全端点 200；阈值设置/重判/internal-manual/cf-scan-meta 均正常
- 待观察：job 79 完成后健康历史快照记录数（SELECT COUNT(*) FROM node_health_history）

## 注意
- NFS 环境 SQLite 有属性缓存延迟（跨进程读秒级滞后），Docker 卷部署无此问题
- PAT nodepool-push 可复用；推送 GitHub 用 git push origin main --tags
