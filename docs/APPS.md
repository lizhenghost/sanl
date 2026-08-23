# Sanl 多端安装包说明

## 📦 三端交付总览

| 平台 | 形态 | 构建方式 | 签名 |
|------|------|----------|------|
| 安卓 | `Sanl-android.apk`（WebView 壳） | GitHub Actions 自动构建 | debug 签名（可直接安装） |
| Windows | `Sanl-windows.zip`（Sanl.exe 单文件服务） | GitHub Actions 自动构建 | 无需签名 |
| iOS / iPadOS | PWA「添加到主屏幕」+ 可选自签 IPA | 见下文限制说明 | — |

## 🤖 安卓 APK

**为什么是独立 APK？** `android/` 目录是一个原生 WebView 壳工程（Java，无第三方重依赖），
加载你的面板地址（默认 `https://lzsanlzhuanhuan.kdns.fr`，可在 `app/src/main/assets/config.json`
修改），支持下拉刷新、返回键导航、订阅文件下载、外部代理链接唤起。

**构建**：GitHub 仓库 → Actions → 「Android APK」→ Run workflow → 下载 artifact；
或打 tag `v*` 自动构建并挂到 Release。

> 说明：当前为 debug 签名（个人使用足够）。若需上架商店/永久签名，需要你自己的 keystore，
> 放入 GitHub Secrets 后可切换 release 构建——这是安卓平台的正常要求，不是缺陷。

## 🪟 Windows

`Sanl.exe` = 面板服务端（FastAPI + SQLite + 前端）单文件打包，双击后自动启动本地服务并打开浏览器。
数据落在 exe 同目录的 `data/` 下。

**构建**：Actions → 「Windows EXE」→ Run workflow；或 tag 触发自动挂 Release。

> 说明：Windows 包内置 Web 服务与前端；测速内核 mihomo 未随包分发（首次测速时按提示放置到
> `bin/mihomo.exe` 即可，或仅使用订阅转换功能无需内核）。

## 🍎 iOS 的如实说明

iOS 与安卓/Windows 不同：**苹果不允许安装未经苹果签名的应用**（App Store / TestFlight /
企业证书 / 开发者证书四条路都需要苹果账号体系，其中前两条要审核、企业证书年费 $299、
开发者个人账号年费 $99 且 7 天需重签）。

因此 iOS 端提供两个务实方案：

1. **PWA（推荐，零成本）**：Safari 打开面板 → 分享 → 添加到主屏幕。全屏运行、有图标，
   体验接近原生 App。manifest.webmanifest 已配置好。
2. **自签 IPA（可选）**：如果你有 Apple 开发者账号（$99/年）或愿意用 AltStore/Sideloadly
   免费侧载（7 天重签），仓库提供 Capacitor 化的 IPA 构建工作流，产物为未签名 IPA 由你自签。
   —— 默认不启用，避免误导以为能直接安装。

这不是偷懒：任何宣称「免签直装 iOS」的工具都依赖企业证书滥用，随时会失效且存在安全风险。
