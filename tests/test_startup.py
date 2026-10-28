"""Plutus schedules nothing any more.

Every recurring job moved to AWS between 2026-10-27 and 2026-10-28 (the
Plutus* schedules in the bookteamworks website repo): calendar channel
renewal, booking completion and reminders, escrow release and the platform
payout; the app-version job was retired. Two of those move money, and two
copies running at once could pay the same row twice -- so a job scheduled
here again is a failure, not a feature.
"""

import asyncio
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, '.')


def test_nothing_is_scheduled():
    from app.main import lifespan

    with patch('app.main.BackgroundScheduler') as scheduler_cls:
        scheduler = MagicMock()
        scheduler_cls.return_value = scheduler

        async def drive():
            async with lifespan(MagicMock()):
                pass

        asyncio.run(drive())

    assert scheduler.add_job.call_count == 0, 'a job is scheduled in Plutus again; it belongs on AWS'
