"""
定时调度器
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import get_scheduler_config
from ..schema import repository
from ..scraper.scraper import Scraper
from ..checker.checker import Checker

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self):
        self.sched = AsyncIOScheduler()
        self.scraper = Scraper()
        self.checker = Checker()
        self.config = get_scheduler_config()

    def start(self):
        """启动调度器"""
        # 抓取任务
        fetch_cron = self.config.get("fetch_cron", "0 */6 * * *")
        self.sched.add_job(
            self._fetch_sources,
            CronTrigger(**self._parse_cron(fetch_cron)),
            id="fetch_sources",
            name="定期抓取数据源"
        )
        
        # 测速任务
        check_cron = self.config.get("check_cron", "30 * * * *")
        self.sched.add_job(
            self._run_check,
            CronTrigger(**self._parse_cron(check_cron)),
            id="run_check",
            name="定期测速检查"
        )
        
        # 清理任务（每天凌晨2点）
        self.sched.add_job(
            self._clean_old_data,
            CronTrigger(hour=2, minute=0),
            id="clean_data",
            name="清理旧数据"
        )

        # 源禁用超时自动恢复（每小时，附录 G：禁用 24h 后重新启用）
        self.sched.add_job(
            self._reenable_sources,
            CronTrigger(minute=10),
            id="reenable_sources",
            name="恢复禁用超时的数据源"
        )

        # GeoIP 出口识别刷新（每 12h，方案 Phase 3 / 附录 I）
        self.sched.add_job(
            self._refresh_geoip,
            CronTrigger(hour="*/12", minute=20),
            id="refresh_geoip",
            name="GeoIP 出口位置刷新"
        )

        self.sched.start()
        logger.info("Scheduler started")

    def _parse_cron(self, cron_str: str) -> dict:
        """解析 cron 表达式为 APScheduler 参数"""
        parts = cron_str.strip().split()
        if len(parts) != 5:
            return {}
        minute, hour, day, month, weekday = parts
        return {
            "minute": minute,
            "hour": hour,
            "day": day,
            "month": month,
            "day_of_week": weekday
        }

    async def _fetch_sources(self):
        """抓取数据源：遍历 DB 启用源 → 抓取+解析+节点入库（指纹去重）→ 记录健康度"""
        logger.info("Starting source fetch (pool import)...")
        try:
            from .pool_importer import run_pool_import
            await run_pool_import(scraper=self.scraper)
        except Exception as e:
            logger.error(f"Fetch failed: {e}")

    async def _run_check(self):
        """运行测速检查（后台执行，不阻塞）"""
        logger.info("Starting speed check...")
        # 使用 create_task 让测速在后台运行，不阻塞 event loop
        import asyncio
        asyncio.create_task(self.checker.run_check())
        logger.info("Speed check started in background")

    async def _reenable_sources(self):
        """恢复禁用超时的数据源（连续失败 5 次禁用 24h 后自动重试）"""
        try:
            reenabled = repository.reenable_expired_sources()
            if reenabled:
                logger.info(f"Re-enabled {reenabled} expired disabled sources")
        except Exception as e:
            logger.error(f"Re-enable sources failed: {e}")

    async def _refresh_geoip(self):
        """定时刷新节点 GeoIP 出口位置"""
        try:
            from ..geoip import refresh_node_geo
            result = await refresh_node_geo(limit=300)
            logger.info(f"GeoIP refresh: {result}")
        except Exception as e:
            logger.error(f"GeoIP refresh failed: {e}")

    async def _clean_old_data(self):
        """清理旧数据"""
        days = self.config.get("auto_clean_days", 7)
        repository.clean_old_jobs(days)
        repository.clean_old_nodes(days)
        logger.info(f"Cleaned data older than {days} days")

    def shutdown(self):
        """关闭调度器"""
        self.sched.shutdown()
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(self.scraper.close())
        except RuntimeError:
            pass
        logger.info("Scheduler stopped")