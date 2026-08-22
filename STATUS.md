# sanl (NodePool) 项目进度报告

**更新时间**: 2026-08-22 UTC（第三轮：前端信息架构 v2）
**项目名**: sanl
**方案版本**: **v2.2.3**（commit 708925c，已推 GitHub + tag）
- **Git 凭据**: ~/.git-credentials 已配 credential store（PAT 至 2026-09-01 有效），`git push origin main` 免密直推

### 🚀 运行态快照
- 进程: python3 main.py @ 127.0.0.1:8899；节点 7766 / CF优选端点 20880+11
- 前端信息架构 v2（b4d1bdd）：📊总览(仪表盘) ｜ 🧩节点池(节点列表/世界地图/**节点源**/订阅输出/令牌管理/测速任务) ｜ 🛰CF优选(**优选端点独立页**←原节点源Tab迁出 / 网段扫描) ｜ 🔁转换工具(订阅转换)
- 表格防裁切 (708925c): .table-container 全局 overflow-x:auto + table min-width:640px（手机桌面模式视口>768px 时媒体查询不触发也能横滑）
- 版本链路: config/app.yaml → GET /api/version → logo 动态显示（修掉 config.py 路径多一级 '..' 的隐藏bug，app.yaml 此前从未被读取）
**域名**: lzsanlzhuanhuan.kdns.fr（Cloudflare Tunnel，HTTPS 200 ✅）
**服务**: http://127.0.0.1:8899（节点池 7378：593 active / 6785 unknown，CF优选端点 3803）
**GitHub**: https://github.com/lizhenghost/sanl（main=bd3694c 已推：白蓝UI+订阅转换+测速进度；PAT nodepool-push 仍有效）

## 2026-08-22 第二轮：导入架构重构（78eb9f7）
### 根因诊断
用户反馈「源加起来应有五六千节点但只有707」+「手动导入被清空」。排查确认四大病灶：
1. **测速回填用 `DELETE FROM nodes` 全清重建** → 每轮只留 subs-check 幸存者（707），手动导入/池内其他节点全部蒸发。
2. **定时器 `_fetch_sources` 只记健康度从不导入节点**，且每次把 node_count 重置为 0（前端全显示 0）。
3. **37 个 CF 优选域名文件混进 subs-check 测速配置** → 垃圾输入拖垮全流程；老僵尸进程（PID 2551）占住 8199 端口导致新任务无限重启循环。
4. **导出 limit 上限 2000**、格式只有 5 种。

### 架构修复（核心）
- **新池导入器** `src/scheduler/pool_importer.py`：遍历 DB 启用源 → 抓取（GitHub 镜像回退链 gh-proxy/ghfast/ghproxy.net）→ 统一解析 → **指纹 upsert 入库**。实测 6 秒解析 **20,528 节点**，去重后入库 **7,222 新节点**。
- **节点唯一指纹** `(type|server|port|凭据)` MD5 + 唯一索引；迁移自动回填历史行并清理 449 条重复。
- **测速结果回填不删库**：`apply_check_results()` 按指纹匹配置 active + 回填速度/延迟/国家；未命中的旧 active 转 inactive；**手动导入节点永不降级、永不删除**。已合成数据验证：总数只增不减 ✅。
- **NULL 指纹陷阱修复**：`NOT IN` 遇 NULL 永假导致失活标记失效——迁移回填后归零。
- **subs-check 配置过滤**：data:/manual/cf-list 类型不再进测速（37 个 CF 文件剔除）；11 个 CF 列表源标记为 cf-list 类型。
- **僵尸进程治理**：启动前 pkill 残留 + `start_new_session` 进程组整组清理 + finally 兜底 terminate。

### 新增能力
- **解析**：sing-box JSON 订阅自动识别；CF 优选 host:port 列表分离到 `cf_endpoints` 表（3803 个端点），不再伪装成 trojan 节点。
- **导出 10 格式**：clash / clash-meta / singbox / v2ray / base64 / txt / mixed / **surge** / **loon** / **quantumult x**（后三者为本次新增生成器）。
- **订阅参数扩展**：`status=all` 全池导出（含未测）、`proto=` 协议过滤（实测 proto=trojan → 970 条）、limit 上限 200→20000。
- **API**：POST `/api/sources/import-all`（后台全量导入按钮）、POST `/api/sources/{id}/reimport`、GET `/api/cf/endpoints`。
- **前端**：格式下拉 5→10 项、「🔄 全量导入」按钮、订阅 URL 类型自动识别（github/http）。

### 验证记录
- 全量导入：43 源成功 / parsed 20528 / inserted 7222 / CF端点 3768 ✅
- 导出格式 HTTP 实测：clash-meta/surge(294行)/loon/qx/mixed/base64/singbox 全通 ✅
- status=all 全池导出 7826 链接 ✅；指纹跨次运行去重 inserted:0 ✅
- 合成测速验证：active 594→1、其余转 inactive、手动节点保留、总数只增 ✅

## 2026-08-22 第一轮（a2aad95）

- **根因**：「数据源加载失败: Cannot set properties of null」= 前端异步竞态——在「数据源」页发起的 fetch 未返回时切到其他页面，回调往已销毁 DOM 写 innerHTML 抛 null 错误并弹误导性 toast。
- **修复**：loadSources/loadCheckHistory/loadDashboard/loadMapData/loadTokens/renderNodeTable/renderNodePage/filterNodes/drawPieChart/drawBarChart 全部加页面切换守卫；loadCheckHistory 文案改为「测速记录加载失败」。
- **HTTPS**：nginx 增加 `X-Forwarded-Proto = http → 301 https` 强制跳转；Cloudflare 边缘证书（Google Trust Services, *.kdns.fr）本就自动可用，https:// 直达。
- **回归**：无头浏览器全页面快速连切无报错弹窗；世界地图正常渲染（38 国/701 定位/707 总节点）。

---

## 📊 当前状态

| 项目 | 状态 |
|------|------|
| **后端 API** | ✅ 运行中 (PID 2915, port 8899)，14 端点回归全通 |
| **数据库** | ✅ 134 节点（active），trojan73/vless38/hy2-15/ss5/vmess3 |
| **测速引擎** | ✅ subs-check 定时任务正常（每小时） |
| **公网访问** | ✅ https://lzsanlzhuanhuan.kdns.fr → 200 |
| **评分系统** | ✅ 多维度评分（v2.1 附录H权重）+ 等级标签 |
| **订阅短链** | ✅ /sub/{token}/{fmt} **五格式**全通（clash/v2ray/singbox/base64/txt）|
| **全协议导入** | ✅ 12 协议：ss/ssr/vmess/vless/trojan/hy2/hysteria/tuic/socks5/http/snell/wireguard |
| **全协议导出** | ✅ Clash 12型 / V2Ray&Base64&Txt 8型链接 / Sing-box 11型 outbound |

---

## ✅ 全协议兼容扩展（2026-08-21 本轮完成）

### 导入侧（`src/api/importer.py`）
- [x] 新增解析：`socks5://` `socks://` `snell://` `ssr://` `hysteria://`(v1) `wireguard://`
- [x] HTTP 代理节点 `http://IP:port`（IP 型判别，域名型走表单/Clash，避免误判订阅 URL）
- [x] JSON 数组导入 `[{"type","server",...}]`（与 Clash proxies 同构）
- [x] 裸域名/`host:port#name`（CF 优选格式 → trojan 占位构造）
- [x] `build_from_form` 表单支持全部 12 协议（含 wireguard 双密钥）
- [x] 订阅 URL 防误判：`https://` 整段行跳过、`parse_host_port` 拒绝含 `/` `?` 的行

### 导出侧（`src/api/subscribe.py` 重写）
- [x] **Clash**：12 协议完整字段（ws/grpc/h2 传输层、REALITY、TLS、SNI、obfs、congestion 等）
- [x] **V2Ray/Base64/Txt**：统一 `generate_links`，8 种 URI（ss/ssr/vmess/vless/trojan/hy2/hysteria/tuic/socks5/http/snell/wireguard）
- [x] **Sing-box**：11 种 outbound（shadowsocks/shadowsocksr/vmess/vless/trojan/hysteria2/hysteria/tuic/socks/http/wireguard）
- [x] **新增 `txt` 明文格式**（多行裸 URI，兼容不支持 Base64 的客户端）
- [x] API 路由 `/api/nodes/subscribe` 与 `/sub/{token}/{fmt}` 均支持 `fmt=txt`

### 前端（`static/index.html`）
- [x] 手动录入类型下拉：+SOCKS5/+HTTP代理/+Snell/+SSR/+WireGuard
- [x] 新增"扩展参数JSON"输入框（承载 wireguard public_key/private_key 等）
- [x] `importSingleNode` 按协议智能映射 secret 字段
- [x] 订阅格式下拉两处（聚合+短链）：+Txt 明文
- [x] 无头浏览器渲染验证：6 协议表单提交 + 5 格式链接生成均通过，JS 无报错

---

## ✅ v2.1 方案缺口补齐（2026-08-21 本轮完成）

### P0 功能缺口（10 项全完成）
- [x] `/sub/{token}/{format}` 订阅短链（clash/v2ray/singbox/base64，支持 min_speed/max_latency/limit/country 筛选，无效/过期 token → 401）
- [x] Token 过期时间（创建时传 `expired_at`）+ `POST /api/token/refresh` 轮换（旧 token 即刻失效）
- [x] `POST /api/sources/{id}/fetch` 手动抓取验证（实测源 #4：HTTP 200 / 1.5MB）
- [x] `GET /api/check/jobs/{id}` 单任务进度查询
- [x] 源健康度自动禁用：连续失败 5 次 → 禁用 24h → 每小时 :10 自动恢复（附录 G）
- [x] 订阅筛选参数 `min_speed`(KB/s) / `max_latency`(ms)
- [x] 订阅页 QR 码扫码导入（qrcodejs CDN，零构建）
- [x] **GeoIP 出口识别**（ip-api.com batch 100/req + 24h 内存缓存 + 限流保护；测速完成后自动刷新 + 每 12h 定时；实测 46/50 识别成功，country_code 入库）
- [x] **多维度评分**：延迟30% + 速度25% + 稳定性20% + 地理15% + 协议10%（附录 H.1），🟢优质/🟡可用/🟠一般/🔴劣质 等级标签（附录 H.2）
- [x] 测速历史趋势：`GET /api/stats/trend` + 仪表盘存活/总数折线图

### P1 上线打磨（7 项全完成）
- [x] 移动端适配（768px/400px 两档响应式：sidebar 横向滚动导航、表格横滚、header 折行）
- [x] GitHub Actions CI（`.github/workflows/ci.yml`：compileall + 路由断言 + 前端 JS 校验）
- [x] Dockerfile + docker-compose.yml + .dockerignore（healthcheck 内置）
- [x] CONTRIBUTING.md（含 GPL 子进程隔离合规说明）
- [x] pyproject.toml（v2.1.0，MIT）
- [x] scripts/install_subscheck.sh（amd64/arm64 自动识别，幂等）
- [x] 节点列表排序（latency/score/speed/created/country × asc/desc，NULL 排最后）+ 等级列

### 明确跳过（方案标注"可选"）
- RSS/博客、Telegram 频道抓取（需 API key）
- GitHub 仓库发现爬虫（附录 G.1 简版延后）
- WebSocket 实时进度（REST 轮询已够用）
- 文档站

---

## 🔌 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/nodes` | 列表：sort/order/offset/min_score/min_speed/max_latency |
| GET | `/api/nodes/subscribe?fmt=` | 免鉴权订阅（四格式+筛选） |
| GET | `/sub/{token}/{fmt}` | **Token 鉴权订阅短链** |
| POST | `/api/tokens` | 建 Token（可传 expired_at） |
| POST | `/api/token/refresh` | Token 轮换 |
| POST | `/api/sources/{id}/fetch` | 手动抓取单源（?trigger_check=true 连带测速） |
| POST | `/api/geoip/refresh?limit=` | 手动 GeoIP 刷新 |
| GET | `/api/check/jobs/{id}` | 任务详情 |
| GET | `/api/stats/trend` | 历史趋势（最近 N 次） |
| GET | `/api/ranking` | 排名（含 grade/emoji 标签） |

## 🗄️ Schema 增量（自动迁移，幂等）

- `nodes.country_code` TEXT / `nodes.fail_count` INT
- `sources.fail_count` INT / `sources.category` TEXT

## 📅 定时任务

| 任务 | 周期 |
|------|------|
| 抓取数据源 | 每 6h（fetch_cron） |
| 测速 | 每小时 :30（check_cron） |
| 测速后 GeoIP | 每次测速完成自动 |
| GeoIP 定时 | 每 12h :20 |
| 源自动恢复 | 每小时 :10 |
| 清理旧数据 | 每天凌晨 2:00 |

## 🚀 待办（下一阶段）

- [ ] CF 优选库方案实施：新增 `cf_endpoints` 表 + `/api/cf/endpoints` 接口 + 前端展示（裸 `ip:port#name` 独立管理，不混入节点池）
- [ ] CF 优选源抓取链路验证（静态文件已生成 youxuan.txt/visa.txt，需确认定时抓取入库完整）
- [ ] README 补截图（仪表盘/地图/订阅二维码）
- [ ] 附录 G.1 GitHub 仓库发现爬虫简版
- [ ] Sing-box `tls:{}` 空对象优化（无 TLS 参数时不输出 tls 字段）
