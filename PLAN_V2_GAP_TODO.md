# PLAN-V2-GAP — 方案v2.1未完成项全部补齐

## P0 功能缺口
- [x] 1. /sub/{token}/{format} 订阅路由（四格式全通，无效/过期 token 401）
- [x] 2. Token 过期时间 + POST /api/token/refresh（轮换后旧 token 即刻失效）
- [x] 3. POST /api/sources/{id}/fetch 手动抓取（源 #4 实测 200/1.5MB）
- [x] 4. GET /api/check/jobs/{id} 任务进度
- [x] 5. 源健康度自动禁用（fail_count≥5 → 禁用24h，每小时自动恢复）
- [x] 6. 订阅筛选 min_speed/max_latency（/api/nodes 与 /sub 均支持）
- [x] 7. QR Code 订阅码（qrcodejs CDN，订阅页扫码导入）
- [x] 8. GeoIP 出口识别（ip-api batch，实测 46/50 节点识别成功；测速后+每12h自动刷新）
- [x] 9. 多维度评分（延迟30/速度25/稳定20/地理15/协议10）+ 🟢🟡🟠🔴等级标签
- [x] 10. 测速历史趋势 GET /api/stats/trend + 仪表盘折线图

## P1 上线打磨
- [x] 11. 移动端响应式适配（768px/400px 两档：sidebar横滚、表格横滚、header折行）
- [x] 12. GitHub Actions CI（语法检查+路由断言+前端JS校验）
- [x] 13. Dockerfile + docker-compose.yml + .dockerignore
- [x] 14. CONTRIBUTING.md
- [x] 15. pyproject.toml (v2.1.0)
- [x] 16. scripts/install_subscheck.sh（amd64/arm64 自动识别）
- [x] 17. 节点列表排序（latency/score/speed/created/country × asc/desc）+ 等级列

## 收尾
- [x] 重启服务 + 全端点回归（18/18 PASS，公网域名 200）
- [ ] STATUS.md 更新
