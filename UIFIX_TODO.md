# UIFIX — 删除用户系统+简化UI+提速

## 一、删除用户系统 ✅
- [x] 精简 src/auth.py（91→44行，删密码/管理员，留 token 鉴权）
- [x] 删除 api.py 中 /auth/register /auth/login /users /users/{id}/role /users/{id}/toggle + UserRegister/UserLogin
- [x] 删除前端"👥用户管理"导航 + renderUsers/loadUsers/showRegisterModal/doRegister/changeRole/toggleUser
- [x] 删除 renderPage switch users 分支
- [x] 保留 Token 鉴权系统（/tokens/validate + 订阅短链）

## 二、简化UI ✅
- [x] 导航 8→7 项（删用户管理）
- [x] 移动端侧边栏已优化（768px 转顶部横向滚动，archive 已做）

## 三、优化访问速度 ✅
- [x] **修复 /vendor 挂载**（根因：后端8899只mount了/static，echarts.min.js/world.json直连404！加 app.mount("/vendor")）
- [x] nginx 开启 gzip（echarts 1MB→332KB，压缩67%）
- [x] /vendor/ 长缓存 30d immutable（archive已有）
- [x] HTML 不缓存确保更新生效（archive已有）
- [x] qrcode defer（订阅页才用）

## 四、回归测试 ✅
- [x] 用户端点 404 / 其余端点 200
- [x] 仪表盘 echarts 图表渲染(canvas×2)
- [x] 世界地图渲染(canvas×1) + 各国节点柱图
- [x] 数据源页 SOCKS5/WireGuard/扩展参数 选项在
- [x] 无用户管理导航
- [ ] git commit + push
