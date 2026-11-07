"""A daily Beat schedule which observes the current database configuration.

Checking configuration does not query the directory or perform a synchronization.
"""
from datetime import datetime
import time
from zoneinfo import ZoneInfo

from celery.beat import PersistentScheduler
from celery.schedules import crontab, schedule, schedstate

from app.core.errors import AppError
from sqlalchemy.exc import SQLAlchemyError
from app.db.session import get_session_factory
from app.security.auth_configuration import configuration, current_setting


class DirectoryDailySchedule(schedule):
    def is_due(self, last_run_at):
        try:
            with get_session_factory()() as session:
                cfg = configuration(current_setting(session))
                if not cfg.sync_enabled:
                    return schedstate(False, 60.0)
                minute, hour, _, _, _ = cfg.sync_schedule.split()
                zone = ZoneInfo(cfg.timezone)
                daily = crontab(minute=minute, hour=hour, nowfun=lambda: datetime.now(zone), app=self.app)
                daily.tz = zone
                state = daily.is_due(last_run_at.astimezone(zone))
                return schedstate(state.is_due, float(state.next))
        except (AppError, SQLAlchemyError):
            return schedstate(False, 60.0)


class DirectoryBeatScheduler(PersistentScheduler):
    """Refresh configured daily times without starving Celery's scheduling heap."""

    max_interval = 60
    _directory_heap_checked_at = 0.0

    def tick(self, *args, **kwargs):
        now = time.monotonic()
        if now - self._directory_heap_checked_at >= 60:
            self._heap = None
            self._directory_heap_checked_at = now
        return super().tick(*args, **kwargs)
