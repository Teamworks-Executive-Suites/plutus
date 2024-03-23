import logging.config
from contextlib import asynccontextmanager

import logfire
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from logfire import PydanticPlugin

from app.auth.views import auth_router
from app.auto.tasks import auto_complete
from app.cal.tasks import update_calendars
from app.cal.views import cal_router
from app.logging import config
from app.pay.views import stripe_router
from app.utils import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retrieve master token from environment variable and add it to known_tokens

    logging.info('startup')

    # Run the tasks immediately on startup
    update_calendars()
    auto_complete()

    # Schedule the tasks to run every hour
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_calendars, 'interval', hours=1)
    scheduler.add_job(auto_complete, 'interval', hours=1)
    scheduler.start()

    yield  # anything before this line runs on before startup and anything after runs on shutdown


app = FastAPI(lifespan=lifespan)

# Logfire
if bool(settings.logfire_token) and settings.testing is False and settings.dev_mode is False:
    logfire.configure(pydantic_plugin=PydanticPlugin(record='all'))
    logfire.instrument_fastapi(app)

# Configure logging
logging.config.dictConfig(config)

# Routers
app.include_router(auth_router)
app.include_router(cal_router)
app.include_router(stripe_router)
