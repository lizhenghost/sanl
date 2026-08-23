# Sanl 运行态快照 — v2.4.0+

> 原 NodePool 已全项目改名 **Sanl**（品牌名），仓库 github.com/lizhenghost/sanl，本地目录 node-pool → sanl

## 当前运行态
- **服务**: `python3 main.py`，PID `pgrep -f "python3 main.py"`，端口 8899，日志 `app.log`，DB `data/nodes.db`
- **最新动态**: 本地 commit `0f8c63a`（未推送 GitHub，待用户确认 PAT）

## 本次修复清单（2026-08-23，用户逐项反馈）
1. ❌→✅ **Token 全部 500（最大痛点）**
   - 根因: `tokens` 表有 `traffic_limit_mb` 列，但 `models.Token` 缺该字段 → `Token(**dict(row))` 抛 `unexpected keyword argument` → `/tokens` `/tokens/validate` `/token/refresh` 等全部 500
   - 修复: `models.py` Token 补 `traffic_limit_mb` 字段；已全库校验所有 dataclass 与 DB 列无 MISSING
2. ❌→✅ **分页只有 4 页**
   - 根因: 前端 `limit=200` 写死 + 本地 slice(200)，最多显示前 4 页
   - 修复: `/api/nodes` 已支持 `limit+offset+sort` 真分页；前端改为 offset 翻页 + 上/下一页 + 总数显示
3. ❌→✅ **Clash 订阅只有 proxies，无分组/规则**
   - `generate_clash` 补全 `proxy-groups`(自动选择 url-test + 各国家组 select + 🚀节点选择) + `rules`(GEOIP,CN,DIRECT / MATCH)
   - 国家分组名由 emoji flag → 中文名（德国/荷兰/美国…），避免客户端显示 □□
   - 已验证 `/sub/{token}/clash` 输出 57 组 + 3 规则
4. ❌→✅ **趋势图全为 0**
   - 根因: `get_score_trend` 读 `result.total/alive/avg_score`，但 check_jobs.result 存的是 `total_nodes`（无 alive）→ 全 0
   - 修复: 兼容 `total_nodes`；测速结果合并 `alive/total/avg_score` 并回填 result
   - 已验证 trend total 恢复 619/544/661
5. ❌→✅ **历史/进度状态矛盾**
   - 根因: 任务入库后从未 `pending→running`，运行期 DB 显示 pending 而内存 progress 显示 running
   - 修复: `run_check` 启动即置 running；`update_check_job` running 时记录 started_at
6. ❌→✅ **侧栏「最近检查 --」**
   - 根因: `refreshSidebarStats` 只更新总节点，从不更新 `last-check`
   - 修复: 拉 `/api/check/history` 取最近 completed 任务时间显示；刷新提速 30s→10s
7. ❌→✅ **流媒体解锁无字段/UI**
   - `stream_flags` 已入库但 API 未返回、前端未展示
   - 修复: `/api/nodes` 返回 `stream_flags`；节点列表新增「解锁」徽章列
8. ❌→✅ **国旗 □□ / 地图标签糊涂**
   - 新增 `flagEmoji(code)`（ISO→旗帜 emoji）+ `countryCell` 修复「□□」；世界地图标签改为节点数≥3 才显示国家名（避免过密）
9. ➕ **新增自定义功能**
   - 源级测速开关: `/api/sources/{id}/speed-test?speed_test=0/1`，前端每个源「⚡测速中/⏸️跳过」按钮（控制哪些源参加延迟/测速）
   - 自定义参与源数量 `max_sources`（只测节点数最多的前 N 个源，显著提速）
   - Token 强制续期: `/api/token/refresh` 加 `renew_days`（过期时间=now+N 天）
10. PWA（manifest+sw+icons+shortcuts）已完整，手机可添加到主屏幕独立运行

## 回归验证（2026-08-23 起新代码）
- `/` 200，`/api/nodes?offset=100` 200，`/api/nodes/stats` total=8803
- `/api/tokens` 200（不再 500）；`renew_days=30` → 新 token 过期=now+30d
- `/sub/{token}/clash` 含 proxy-groups+rules，国家名中文
- `/api/sources?enabled=true` 返回 speed_test 字段，source1 切换 ok
- 全部改动 `py_compile` 通过，启动无 Traceback
