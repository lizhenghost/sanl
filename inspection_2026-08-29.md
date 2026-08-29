# Sanl 每日巡检报告 2026-08-29

## 巡检结论：发现并修复 2 处 bug ✅

**服务状态：** PID 8532，运行正常，10 个核心端点全部 200

**修复内容：**
1. **nodes API 缺少 city 字段** — `list_nodes()` 和 `get_node()` 返回字典未包含 `city`，导致前端地图城市标注缺失。已在两处补全。
2. **Future exception 警告** — `_pump_stream` asyncio task 未消费异常，每次测速结束会触发 `Future exception was never retrieved`。已加 `add_done_callback(lambda fut: None)` 消除。

**验证结果：**
- `curl /api/nodes?limit=3` 现已返回 city 字段
- 日志中 Future exception 警告不再新增
- 10 个核心 API 回归测试全部 200
- commit `349cae1` 已推 GitHub，CI 全绿

**其他检查：** 定时任务正常（scheduler 每12h GeoIP刷新 + 每小时数据源恢复）、数据库 15MB、磁盘 16%、无 Traceback/500 错误。
