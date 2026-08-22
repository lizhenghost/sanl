# 贡献指南

感谢关注 Sanl！欢迎以任何形式贡献。

## 开发环境

```bash
git clone <repo> && cd node-pool
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/install_subscheck.sh   # 下载测速引擎二进制
python main.py                   # http://localhost:8899
```

## 目录导览

```
src/api/         FastAPI 路由（REST + /sub 订阅短链）
src/checker/     subs-check 桥接（子进程调用，勿合并进主程序）
src/scraper/     免费源抓取器
src/geoip.py     ip-api.com 出口识别
src/schema/      SQLite 模型/仓库层
src/scheduler/   APScheduler 定时任务
static/          单文件前端（零构建，直接改 HTML）
```

## 规范

- **许可**：主程序 MIT。subs-check 为 GPL-3.0，必须保持**子进程隔离调用**，不得源码级合并或静态链接。
- **前端**：保持零构建（无 npm/webpack），库走 CDN。
- **提交**：一个 PR 一件事；消息格式 `type: summary`（feat/fix/docs/refactor/test）。
- **测试**：提交前跑 `python -m compileall src -q`，前端改动后确认页面无 JS 报错。
- **数据源 PR**：只收公开免费的公益源，附上仓库星数与更新频率说明。

## 报告问题

Issue 请附：Python 版本、`/api/nodes/stats` 输出、相关日志（`docker logs sanl` 或终端输出）。

## 行为准则

保持友好、尊重、聚焦技术。
