# Sanl 每日巡检报告 2026-08-30

## 巡检结论：发现并修复 Future exception 问题 ✅

**服务状态：** PID 13972（已重启应用修复），10 核心端点全部 200

**修复内容：**
- **Future exception 警告消除** — `_pump_stream` asyncio task 在旧进程中未消费异常，每次测速产生 20+ 条 `Future exception was never retrieved` 警告。已重启服务应用 `add_done_callback(lambda fut: None)` 修复，新日志中该警告已归零。
- **city 字段验证通过** — `/api/nodes` 已正确返回城市名（Phoenix/Vancouver/Tallin 等），active 节点 city 覆盖率 100%。

**验证结果：**
- 10 个核心 API 回归测试全部 200
- 日志中 Future exception 计数：0（修复前 151+）
- 无 Traceback/500 错误
- 定时任务正常（数据源恢复 cron 每小时执行）
- 数据库 15MB，磁盘 16%，节点 9255 总/活跃节点 city 100% 覆盖

**数据源：** 86 个数据源已配置，个别外部 API（addressesapi.090227.xyz）返回 500 为源端问题，非 Sanl 代码 bug。
