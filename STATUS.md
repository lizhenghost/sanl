# sanl (NodePool) 项目进度报告

**更新时间**: 2026-08-21 UTC
**项目名**: sanl
**方案版本**: v2.1 + 全协议扩展（2026-08-21 本轮）
**域名**: lzsanlzhuanhuan.kdns.fr（Cloudflare Tunnel，公网 200 ✅）
**服务**: http://127.0.0.1:8899（PID 2915）
**GitHub**: https://github.com/lizhengost/sanl（Public, tag v2.1.0）

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
