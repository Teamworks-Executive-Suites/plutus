import logging.config
from contextlib import asynccontextmanager

import logfire
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.auth.views import auth_router
from app.auto.cal_tasks import auto_check_and_renew_channels
from app.auto.tasks import auto_complete_and_notify
from app.cal.views import cal_router
from app.cal.webhooks import cal_webhook_router
from app.logging import config
from app.pay.views import stripe_router
from app.utils import app_logger, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger.info('startup')

    auto_check_and_renew_channels(force_renew=True)
    auto_complete_and_notify()

    scheduler = BackgroundScheduler()
    scheduler.add_job(auto_check_and_renew_channels, 'interval', hours=1)
    scheduler.add_job(auto_complete_and_notify, 'interval', hours=1)
    scheduler.start()
    app_logger.info('Scheduler initialized and started')

    yield


app = FastAPI(lifespan=lifespan)

if bool(settings.logfire_token) and settings.testing is False and settings.dev_mode is False:
    logfire.instrument_fastapi(app)
    logfire.configure(
        send_to_logfire=True, token=settings.logfire_token, pydantic_plugin=logfire.PydanticPlugin(record='all')
    )

    FastAPIInstrumentor.instrument_app(app)

logging.config.dictConfig(config)

app.include_router(auth_router)
app.include_router(cal_router)
app.include_router(cal_webhook_router)
app.include_router(stripe_router)
