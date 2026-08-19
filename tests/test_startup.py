"""Startup must not put slow work on the path to binding the port.

Heroku kills a web dyno that has not bound ``$PORT`` within 60 seconds. The scheduled
jobs walk the whole transactions ledger, so running them inline in ``lifespan`` meant
boot time grew with the size of the ledger. That was invisible while
``process_transactions`` was accidentally a no-op; the moment it started doing real work
the dyno stopped booting at all and the backend went dark.

These tests drive the lifespan with asyncio.run rather than pytest-asyncio, which is not
among the pinned test dependencies.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import DEFAULT, MagicMock, patch

sys.path.insert(0, '.')

JOB_NAMES = (
    'auto_complete_and_notify',
    'process_transactions',
    'process_platform_payout',
    'auto_check_and_renew_channels',
    'auto_update_cloud_version',
)


def _enter_and_exit_lifespan():
    """Run the lifespan through startup and shutdown, returning the fake scheduler."""
    from app.main import lifespan

    with patch('app.main.BackgroundScheduler') as scheduler_cls:
        scheduler = MagicMock()
        scheduler_cls.return_value = scheduler

        async def drive():
            async with lifespan(MagicMock()):
                pass

        asyncio.run(drive())
        return scheduler


def test_lifespan_does_not_call_jobs_inline():
    """Entering the lifespan must not invoke any job directly."""
    # DEFAULT, not MagicMock(): patch.multiple only hands back mocks it created itself,
    # so passing instances would yield an empty dict and a vacuously passing test.
    with patch.multiple('app.main', **{name: DEFAULT for name in JOB_NAMES}) as jobs:
        assert set(jobs) == set(JOB_NAMES), 'the patch did not take'
        _enter_and_exit_lifespan()
        for name, job in jobs.items():
            assert job.call_count == 0, f'{name} ran inline during startup and would delay binding $PORT'


def test_every_job_is_scheduled_to_run_shortly_after_boot():
    """Deferring the jobs must not mean losing the run-once-at-startup behaviour."""
    from app.main import STARTUP_JOB_DELAY_SECONDS

    before = datetime.now(timezone.utc)
    scheduler = _enter_and_exit_lifespan()
    after = datetime.now(timezone.utc)

    scheduled = {call.args[0].__name__ for call in scheduler.add_job.call_args_list}
    assert scheduled == set(JOB_NAMES), 'every job should still be registered'

    scheduler.start.assert_called_once()

    for call in scheduler.add_job.call_args_list:
        first_run = call.kwargs['next_run_time']
        assert first_run >= before + timedelta(seconds=STARTUP_JOB_DELAY_SECONDS)
        assert first_run <= after + timedelta(seconds=STARTUP_JOB_DELAY_SECONDS)
        # Money-moving jobs must never have two copies in flight at once.
        assert call.kwargs['max_instances'] == 1
        assert call.kwargs['coalesce'] is True
