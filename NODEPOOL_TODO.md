# sanl (NodePool) 项目进度跟踪

## 目标
构建一个免费节点池聚合平台，支持多源订阅、自动测速、节点管理。
**GitHub 仓库名**: sanl  
**域名**: lzsanlzhuanhuan.kdns.fr  
**服务器**: 47.84.122.196 (Debian 12)

---

## ✅ 已完成

### 核心框架
- [x] FastAPI 应用结构
- [x] SQLite 数据库 schema (3张表)
- [x] 数据模型定义
- [x] 配置文件管理

### API 接口 (8个端点)
- [x] GET /api/nodes — 节点列表
- [x] GET /api/nodes/stats — 节点统计
- [x] GET /api/sources — 数据源列表
- [x] POST /api/sources — 添加数据源
- [x] PUT /api/sources/{id}/enable — 启用/禁用
- [x] DELETE /api/sources/{id} — 删除数据源
- [x] POST /api/check/run — 手动触发测速
- [x] GET /api/check/history — 检查历史
- [x] GET /api/nodes/subscribe — 订阅导出 (Clash YAML)

### 前端界面
- [x] 仪表盘 (ECharts 图表)
- [x] 节点列表 (带筛选)
- [x] 数据源管理
- [x] 测速任务历史

### 部署
- [x] nginx 反向代理配置
- [x] 端口 8899 暴露
- [ ] 域名 DNS 解析 (待用户配置)

### 数据
- [x] 已添加 1 个数据源 (V2RayAggregator)
- [x] 已抓取并入库 211 个节点

---

## 🔄 进行中

### 🔴 高优先级
- [ ] **修复测速状态保存** — 节点 status 全是 unknown
  - subs-check 正在运行测速
  - 需要修复 `_parse_and_store_results` 函数
  - 正确解析 name 字段中的速度信息 (如 `🇺🇸US_1|304KB/s`)
  - 更新节点的 status, latency, download_speed 字段

### 🟡 中优先级
- [ ] 添加更多免费数据源
- [ ] 修复定时任务调度
- [ ] 清理 subs-check 端口冲突

### 🟢 低优先级
- [ ] 支持 SingBox/V2Ray 格式订阅
- [ ] 添加 GeoIP 国家统计
- [ ] 添加 HTTPS (Let's Encrypt)
- [ ] 前端优化 (分页、搜索、排序)

---

## 📋 待完成

### 部署准备
- [ ] systemd 服务配置
- [ ] 日志轮转
- [ ] 健康检查端点

### 开源准备
- [ ] README.md 完善
- [ ] LICENSE (MIT)
- [ ] GitHub 仓库初始化
- [ ] 移除敏感配置

---

## 🔧 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI |
| 数据库 | SQLite |
| 测速引擎 | subs-check (Go 二进制) |
| 调度 | APScheduler |
| 前端 | 纯 HTML/CSS/JS + ECharts |
| 反向代理 | nginx |

---

## 🌐 访问地址

| 环境 | 地址 | 状态 |
|------|------|------|
| 本地 | http://localhost:8899 | ✅ 运行中 |
| 公网 IP | http://47.84.122.196:8899 | ✅ 可访问 |
| 域名 | http://lzsanlzhuanhuan.kdns.fr | ❌ DNS 待配置 |

---

## 📝 备注

- MVP 基础功能已完成，核心框架搭建完毕
- 主要问题是测速结果没有正确保存到数据库
- 需要用户配置域名 DNS 解析
- 项目计划开源，仓库名: sanl

---
最后更新: 2026-08-20 12:45 UTC
