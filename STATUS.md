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


## 本轮：性能与可用性优化（2026-08-23）

### ✅ 后端 TTL 缓存层（P0，用户强调"多命中缓存，不要不命中缓存"）
- 新增 `src/api/cache.py`：进程内 TTL 缓存装饰器 `@cached(ttl)` + `invalidate_all()` + `cache_stats()`
  - key = 函数名 + 全部可序列化参数（自动区分 limit/offset/sort 等不同查询）
  - 命中/未命中计数供面板展示
- 已加缓存的读端点：`/nodes/stats`(5s)、`/map`(5s)、`/sources/health`(5s)、`/ranking`(3s)、`/stats/trend`(5s)、`/check/history`(3s)、`/sources`(3s)、`/nodes`(3s)
- 失效策略：
  1. HTTP 中间件：任何非 GET/HEAD/OPTIONS 请求完成后 `invalidate_all()`（写操作低频，清空保正确且命中率高）
  2. 后台任务（抓取/测速不经过 HTTP）：在 `checker.apply_check_results` 后、`pool_importer` 入库后手动 `invalidate_all()`
- 新增 `/api/cache/status` 返回 hit/miss/size；实测连续请求命中 16 / 未命中 12（冷启动后攀升）
- 前端新增右下角「⚡缓存」浮标，点击弹窗显示命中率

### ✅ 前端轮询节流（D2）
- 全局任务轮询改为**自适应**：有活动任务 2.5s，空闲降频到 10s（`try/finally` + `_gtTimer` 自调度）
- 后端缓存兜底，空闲轮询几乎零查询成本

### ✅ GeoIP 刷新优化（C3，原误报 "0/300"）
- 排查确认：**非查询失败**——active 645 节点中 638 个已正确填充 country，`0/300` 只是"取的 300 个全是已正确节点无变化"
- 优化：新增 `repository.list_nodes_missing_geo()`，刷新时**只补国家缺失的节点**，跳过已正确节点
- 实测：缺失 7 个节点一次性补全（updated=7, looked_up=5），日志不再出现误导性 0/300

### ✅ 核验已实现的既有能力（确认无需重复开发）
- **C5 订阅默认可用节点**：`/sub/{token}/{fmt}` 默认 `status=active`，走 `get_ranking`（只出测速通过的高分节点），不吐死链
- **E1 CF 优选端点利用**：`/api/cf/endpoints` 已具备 ISP 分类（all 19801/mobile 5093/telecom 1852/unicom 2813）+ IP 版本分类 + 按延迟排序 + 扫描测速（实测快速端点 latency 3ms）；CF 端点无协议只能作"优选 IP 参考"，配合 ws/reality 协议节点作 server 优化
- **E3 节点保活**：`apply_check_results` → `mark_missing_inactive` 已实现——源消失的 auto 节点每轮降级 inactive，连续 3 轮失败自动进 dead（黑名单）；手动导入节点永不降级（设计权衡）

### 回归
- 14 个核心端点（nodes/stats/map/ranking/sources/sources-health/trend/check-history/nodes/tasks/cf-endpoints/cache-status/tokens-stats/convert-formats/openapi）全 200
- 全改动 `py_compile` 通过，启动无 Traceback，scheduler 4 个任务正常注册
