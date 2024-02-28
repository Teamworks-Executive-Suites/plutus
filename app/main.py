import logging

import logfire
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

from app.auto.tasks import auto_complete
from app.cal.tasks import update_calendars
from app.auth.views import auth_router
from app.cal.views import cal_router
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

if bool(settings.logfire_token):
    logfire.configure()
    logfire.instrument_fastapi(app)

app.include_router(auth_router)
app.include_router(cal_router)
app.include_router(stripe_router)
