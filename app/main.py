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
from app.utils import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retrieve master token from environment variable and add it to known_tokens

    logging.info('startup')

    # Run the tasks immediately on startup
    auto_complete_and_notify()
    auto_check_and_renew_channels()

    # Schedule the tasks to run every hour
    scheduler = BackgroundScheduler()
    scheduler.add_job(auto_complete_and_notify, 'interval', hours=1)
    scheduler.add_job(auto_check_and_renew_channels, 'interval', hours=1)
    scheduler.start()

    yield  # anything before this line runs on before startup and anything after runs on shutdown


app = FastAPI(lifespan=lifespan)

# Logfire
if bool(settings.logfire_token) and settings.testing is False and settings.dev_mode is False:
    logfire.instrument_fastapi(app)
    logfire.configure(
        send_to_logfire=True, token=settings.logfire_token, pydantic_plugin=logfire.PydanticPlugin(record='all')
    )

    FastAPIInstrumentor.instrument_app(app)

# Configure logging
logging.config.dictConfig(config)

# Routers
app.include_router(auth_router)
app.include_router(cal_router)
app.include_router(cal_webhook_router)
app.include_router(stripe_router)
