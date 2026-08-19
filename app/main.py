import logging.config
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import logfire
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.admin.views import admin_router
from app.auth.views import auth_router
from app.auto.cal_tasks import auto_check_and_renew_channels
from app.auto.payout_task import process_platform_payout
from app.auto.tasks import auto_complete_and_notify
from app.auto.transaction_tasks import process_transactions
from app.auto.version_tasks import auto_update_cloud_version
from app.cal.views import cal_router
from app.cal.webhooks import cal_webhook_router
from app.logging import config
from app.pay.views import stripe_router
from app.utils import app_logger, settings

# Long enough for uvicorn to bind and Heroku to mark the dyno up before the ledger
# walks start competing for the process.
STARTUP_JOB_DELAY_SECONDS = 15


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger.info('startup')

    # These jobs used to run inline here, which put a full ledger walk on the critical
    # path to binding $PORT. That was survivable only while process_transactions was
    # silently a no-op; once it started doing real work it took ~45s on its own and the
    # dyno was killed for boot timeout before it ever served a request.
    #
    # Scheduling them a few seconds out keeps the "run once at startup" behaviour while
    # letting the server bind immediately. APScheduler runs them on its own threads.
    first_run = datetime.now(timezone.utc) + timedelta(seconds=STARTUP_JOB_DELAY_SECONDS)

    scheduler = BackgroundScheduler()
    for job, hours in (
        (auto_complete_and_notify, 1),
        (process_transactions, 1),
        (process_platform_payout, 1),
        (auto_check_and_renew_channels, 12),
        (auto_update_cloud_version, 1),
    ):
        scheduler.add_job(
            job,
            'interval',
            hours=hours,
            next_run_time=first_run,
            # A run that overruns its interval must not stack a second copy on top of
            # itself — these jobs move money and are not safe to run concurrently.
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
        )

    scheduler.start()
    app_logger.info('Scheduler initialized and started')

    yield


app = FastAPI(lifespan=lifespan)

if bool(settings.logfire_token) and settings.testing is False and settings.dev_mode is False:
    logfire.instrument_fastapi(app)
    logfire.configure(send_to_logfire=True, token=settings.logfire_token)
    logfire.instrument_pydantic()

    FastAPIInstrumentor.instrument_app(app)

logging.config.dictConfig(config)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(cal_router)
app.include_router(cal_webhook_router)
app.include_router(stripe_router)
