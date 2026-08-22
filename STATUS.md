# Sanl 运行态快照 — v2.4.0

> 原 NodePool 已全项目改名 **Sanl**（品牌名），仓库 github.com/lizhenghost/sanl，本地目录 node-pool → sanl

## 当前运行态
- **服务**: `python3 main.py`，PID 见 `pgrep -f "python3 main.py"`，端口 8899，日志 /tmp/sanl.log
- **最新功能** (本次提交):
  - ⚡ 测速维度可选: `latency`(仅延迟) / `speed`(延迟+速度) / `full`(全量含流媒体)
    - API: `POST /api/check/run?trigger=manual&mode=latency` + 可选 JSON body 参数覆盖(白名单)
    - 前端测速页新增模式三选卡 + 高级参数覆盖面板
    - 定时测速默认模式由 `config/app.yaml → scheduler.check_mode` 控制(默认 speed)
  - 🚀 测速提速: 结果文件固定等60s → 动态稳定检测(约15s)；轮询 5s→3s
    - **实测仅延迟模式 97 秒跑完 21362 节点全流程**（原全量模式 30-60 分钟）
    - latency 模式跳过流媒体检测/IP重命名/速度测试三大耗时项
  - 🏷️ 全项目品牌 NodePool → Sanl（前端标题/logo、API 文档、日志、UA、构建脚本、CI、docker-compose）
  - 📱 安卓 PWA App: manifest + Service Worker(根scope) + 图标(192/512/maskable) + 快捷方式
    - 手机浏览器访问 → 添加到主屏幕 → 全屏独立运行；API 永远走网络，静态资源离线缓存
- **回归**: 核心 API 全 200；/sw.js 正确 MIME + Service-Worker-Allowed: /；5连测首页 200；0 Traceback
