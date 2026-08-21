# NodePool — 免费节点池聚合平台

> Python FastAPI + subs-check 引擎，纯静态前端，SQLite 存储，MIT 许可，零预算部署

## ✨ 功能特性

### 核心功能
- 🔄 **多源聚合** — 15+ 预置免费节点源一键导入，支持手动添加 / 粘贴 Base64 导入
- ⚡ **真实测速** — 桥接 subs-check（Go/mihomo 内核）做真实协议握手测速，非伪测速
- 📊 **质量评分** — 基于下载速度 + 延迟的 0-100 综合评分与排名
- 📥 **多格式订阅** — Clash YAML / V2Ray / Sing-box / Base64 四种格式输出
- ⏰ **定时调度** — APScheduler 自动抓取（每6h）+ 测速（每小时）+ 数据清理

### Phase 2 平台增强
- 🔑 **Token 鉴权系统** — 订阅链接 Token 保护，支持创建/禁用/删除/轮换
- 👥 **多用户系统** — 用户注册/登录，admin/user 角色权限
- 🌍 **世界地图可视化** — ECharts 世界地图节点分布 + 各国统计
- 📡 **数据源管理面板** — 预置源批量导入、健康度监控、粘贴导入
- 🚀 **自动 Release 构建** — GitHub Actions 打包发布 tar.gz/zip

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行
python main.py
```

访问 `http://localhost:8899` 查看仪表盘。

## 目录结构

```
node-pool/
├── main.py                 # 主入口
├── requirements.txt        # Python 依赖
├── subs-check             # subs-check 二进制（运行时下载）
├── .github/workflows/     # GitHub Actions 自动发布
├── config/
│   ├── app.yaml           # 应用配置
│   └── subs-check.yaml    # subs-check 配置（自动生成）
├── data/
│   └── nodes.db           # SQLite 数据库（自动创建）
├── output/                # subs-check 输出目录
├── presets/
│   └── free_sources.json  # 预置免费源清单
├── scripts/
│   └── build_release.py   # 发布打包脚本
├── static/                # 前端静态文件
│   ├── index.html         # 单页应用（8 个页面）
│   └── worldmap.js        # 地图模块
└── src/
    ├── auth.py            # 认证鉴权模块
    ├── mapdata.py         # 世界地图坐标数据
    ├── config.py          # 配置加载
    ├── schema/            # 数据模型 + SQLite
    ├── scraper/           # 免费源抓取器
    ├── checker/           # subs-check 测速引擎
    ├── scheduler/         # 定时调度
    └── api/               # FastAPI 路由
```

## API 端点

### 核心接口
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/nodes` | 节点列表（筛选/分页） |
| GET | `/api/nodes/stats` | 节点统计 |
| GET | `/api/ranking` | 节点评分排名 |
| GET | `/api/nodes/subscribe?fmt=clash\|v2ray\|singbox\|base64` | 多格式订阅输出 |
| POST | `/api/check/run` | 手动触发测速 |
| GET | `/api/check/history` | 测速历史 |

### 数据源管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sources` | 数据源列表 |
| GET | `/api/sources/presets` | 预置免费源列表 |
| POST | `/api/sources/batch-import` | 批量导入预置源 |
| POST | `/api/sources/raw-import` | 粘贴 Base64 导入 |
| GET | `/api/sources/health` | 源健康度报告 |

### Token 鉴权
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tokens` | 创建 Token |
| GET | `/api/tokens` | Token 列表 |
| PUT | `/api/tokens/{id}/toggle` | 启用/禁用 |
| DELETE | `/api/tokens/{id}` | 删除 |

### 用户系统
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册用户 |
| POST | `/api/auth/login` | 登录（返回会话 token） |
| GET | `/api/users` | 用户列表 |
| PUT | `/api/users/{id}/role` | 修改角色 |

### 可视化
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/map` | 世界地图数据（国家坐标+散点） |

## 使用示例

### 创建订阅 Token 并使用
```bash
# 创建 Token
curl -X POST http://localhost:8899/api/tokens \
  -H 'Content-Type: application/json' \
  -d '{"name": "我的手机", "permissions": "read"}'

# 带 Token 获取订阅
curl "http://localhost:8899/api/nodes/subscribe?fmt=clash&limit=100" \
  -H "Authorization: Bearer np_xxxx..."
```

### 导入预置免费源
```bash
# 查看预置源
curl http://localhost:8899/api/sources/presets

# 批量导入（按 index）
curl -X POST http://localhost:8899/api/sources/batch-import \
  -H 'Content-Type: application/json' \
  -d '{"source_ids": [0,1,2,3]}'
```

## 发布

打 tag 即自动构建发布：

```bash
git tag v1.0.0
git push origin v1.0.0
# → GitHub Actions 自动打包 tar.gz/zip 并创建 Release
```

本地构建：`python scripts/build_release.py`

## License

MIT。subs-check (GPL-3.0) 以子进程方式隔离调用，主程序保持 MIT。
