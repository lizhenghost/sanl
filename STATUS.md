# Sanl 运行态快照 — v2.4.0+

> 原 NodePool 已全项目改名 **Sanl**（品牌名），仓库 github.com/lizhenghost/sanl，本地目录 node-pool → sanl

## 当前运行态
- **服务**: `python3 main.py`，PID `pgrep -f "python3 main.py"`，端口 8899，日志 `app.log`，DB `data/nodes.db`
- **最新动态**: 本地 commit `48a86a0`（已推 GitHub），job 105 完成：active **12→44**（+3.7×），协议 ss:27/vless:11/trojan:3/vmess:2/http:1，候选 7629/存活 53/评分 51.6

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

## 他人 bug 报告核实与修复（commit 84495a4，推至 main）

对 `sanl_bug_report.md` 逐条「实测核实」而非盲信，共 3 项真实修复 + 4 项判定为误报/设计。

### ✅ 真实修复（3 项）
1. **SPA 路由 fallback**（`src/api/api.py`）
   - 问题：地址栏直接输入/刷新 `/nodes`、`/dashboard`、`/cf`、`/tokens`、`/speedtest`、`/convert` 返回 404 空白。
   - 修复：新增 `@app.get("/{full_path:path}")` 兜底路由，凡未命中 `/api`、`/sub`、`/static`、`/vendor`、`/openapi.json`、`/docs`、`/sw.js`、`/manifest`、`/favicon.ico` 的 GET 一律返回单页 `index.html`，由前端 JS 接管渲染。
   - 实测：以上路径全部 200（加载前端）；`/api/nodes/stats`、`/static/index.html`、`/sw.js`、`/openapi.json`、`/api/cache/status` 均不被 fallback 拦截（仍各自 200）。

2. **PWA 安卓端更新机制**（`static/sw.js`）
   - 问题：SW 用 cache-first（`sanl-v1`），安卓已安装的 PWA 会一直拿到旧版前端（缓存浮标/自适应轮询等改动看不到）。
   - 修复：`CACHE` 升版 `sanl-v1` → `sanl-v2`（activate 时删除旧缓存重建，强制拉新）；导航请求 `mode==='navigate'` 改 network-first（失败回退缓存），保证每次打开首页优先网络拿最新。
   - 影响：安卓端用户下次打开 PWA 会自动更新到最新前端。

3. **node_data JSON 容错解析**（`src/schema/repository.py`）
   - 问题：`list_nodes`/`list_nodes_missing_geo` 等 5 处 `json.loads(node_data)` 无 try，若 DB 中任一条 node_data 为空/坏 JSON，会导致整个节点列表接口 500。
   - 修复：新增 `_parse_node_data()`（None/非 dict/坏 JSON 均安全回退空 dict），统一替换 5 处调用；任一条坏数据不再拖垮列表接口。

### ⚪ 判定为误报 / 设计（不改动）
| 报告结论 | 核实结果 |
|---|---|
| 静态资源缺失 `main.js`/`app.js`/`style.css` | **误报**：前端为单页 `index.html`（JS/CSS 全内联），`static/` 只有 `index.html`+`worldmap.js`+`manifest`+`sw.js`，无上述文件是设计 |
| API 端点 75% 缺失 | **误报**：OpenAPI 实际 58 个端点；报告列的 `/api/pools`、`/api/config`、`/api/subscribe`、`/api/speedtest` 等命名在项目里并不存在 |
| `/api/convert`、`/api/cf/scan` 405 | **误报**：这两个本就是 POST 端点（报告用 GET 测导致 `405 Method Not Allowed`，属正常） |
| 节点 `subscribe_url`/`node_data`/`created_at` 缺失 | **安全设计**：`/api/nodes` 刻意只暴露展示字段，**不返回** `node_data`（含 password，防泄漏）与 `subscribe_url`；`Node` 模型将其默认成空串。DB 实测 8803 条全部完整（`subscribe_url`/`node_data`/`created_at`/`updated_at` 均非空，node_data 为合法 JSON） |

### ⚠️ 一项确认的外部限制（非本项目 bug）
- **`latency` 全为 NULL**：all.yaml 节点名为 `🇺🇸US_1|400KB/s`（仅国家+速度），**subs-check 命名模板不含延迟**（外部二进制）；节点条目本身也无 latency 字段 → 无法从 subs-check 输出可靠提取延迟。
- 已确认不造成伤害：`apply_qualified_latency` 只对 `latency IS NOT NULL` 判定，latency=NULL 的节点不会被误标 inactive（否则 active 不会保持在 645）。
- 节点质量已由 `download_speed`（645/645 全有值）充分评估，**不影响订阅生成与节点工作**。不引入伪造延迟。

### 前端交互核实
- `pollGlobalTasks`/`refreshSidebarStats`/`renderNodes`/`renderMap`/`loadSources`/`subscribe`/`echarts` 等关键逻辑均在 `index.html` 内联，页面非空壳；`/manifest.webmanifest`、`/vendors/echarts.min.js`、`/vendor/qrcode.min.js`、`/static/icons/*` 全部 200。
- 结论：报告称「交互功能无法工作」为**误报**（其因 `main.js`/`app.js` 404 直接推断而未实际加载页面）。

### 回归
- 13 个核心端点全 200：`/api/nodes/stats`、`/api/map`、`/api/ranking`、`/api/sources`、`/api/sources/health`、`/api/stats/trend`、`/api/check/history`、`/api/nodes`、`/api/cf/endpoints`、`/api/cache/status`、`/api/convert/formats`、`/sw.js`、`/nodes`。
- `py_compile` 通过；`node --check static/sw.js` 通过；后端重启正常（PID 18197）。

## 节点统计失真修复（commit dec75f7，推至 main）

用户反馈"3万节点只有600可用、总节点显示700多"。逐环节实测排查，根因 + 修复如下。

### 数据链路实测（subs-check 日志）
```
源报告节点数 ~3万(含CF列表+跨源重复)
  → subs-check 实际拉取 21515
  → 去重后 8034
  → 测活存活 1085        ← 免费聚合池真实死亡率 ~86%
  → 过测速(min-speed) 可用 633→750   ← 免费池客观水平
```

### 根因：unknown 状态永不降级（统计失真元凶）
`mark_missing_inactive` 的 `WHERE status IN ('active')` **漏掉 unknown**——入库后从未存活的节点每轮被 subs-check 测过（死亡不在 all.yaml），但永远停在 unknown、fail_count 永不累计、永不进黑名单。曾积累 **unknown=7417 占全池 84%**。

### ✅ 修复清单（commit dec75f7）
1. **状态机修复**：`mark_missing_inactive` 纳入 unknown；fail_count 统一 +1；连续 3 轮失败 → dead 黑名单。
2. **stats 新口径**：`total` = active+inactive+unknown（有效池，不含黑名单）；新增 `pool_total`（物理总数）与 `dead` 字段。
3. **清理死链源**：禁用 10 个已验证 404 的 discover 源（zhuhaiuk/junjun266/littlebais/Au1rxx 全 URL）+ 禁用 #13（V2RayAggregator Clash 格式，与 #4 完全重复）。
4. **新增可用源**（均实测 200）：mahdibland Eternity.txt（精品筛选线）/ mfuu/v2ray / Epodonios trojan.txt。
5. **min-speed 256→128**：存活但中速的节点也算可用（免费池稀缺，128KB/s 满足基础代理）。

### 效果（修复后首轮测速实测）
- unknown: **7417 → 0**，全部正确归类 inactive
- 可用: **633 → 750**（+18%）
- 统计口径：total=8882 / active=709 / inactive=8173 / dead=0（dead 将随 fail_count 累计逐步产生）
- 订阅输出回归：/sub/{token}/clash 1.38MB、base64 1.07MB、txt 800KB 全 200

### 关于"3万多个节点"的口径解释
- 3万+ = 各源页面 node_count 原始总和（含 CF IP 列表类源 + 跨源重复 + 同仓库多格式）
- cf_endpoints 表 2.9 万是 CF 优选 IP（无协议密码，非代理节点，独立管理层）
- 真实去重代理节点 8871 个；免费聚合池能存活的比例就是 ~13%，这是所有免费订阅 aggregator 的客观水平
15. ❌→✅ **修复后 active 节点验证（job 105）**
   - job 105 候选 7629，存活 53，active 44（之前 12），**提升 3.7 倍**
   - active 协议：ss:27, vless:11, trojan:3, vmess:2, http:1
   - 延迟分布：0-100ms:9, 100-200ms:10, 200-400ms:10, 400-800ms:15
   - 仍低于 subs-check 750 的原因：候选池 http/vless 仍偏低（importer 已修复域名型解析，但 subs-check 订阅中的 http/vless 节点在管线中仍被部分丢弃）
   - 结论：候选池层面仍需进一步优化（尤其 vless），引擎内核探活能力已验证合格（B9 98%）
