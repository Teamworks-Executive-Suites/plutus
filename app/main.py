import sys

print(sys.executable)

import logging
import os

from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

from app.auto.tasks import auto_complete
from app.cal.tasks import update_calendars
from app.settings import Settings
from app.auth.views import auth_router
from app.cal.views import cal_router
from app.pay.views import stripe_router

settings = Settings()

known_tokens = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retrieve master token from environment variable and add it to known_tokens

    logging.info('startup')

    master_token = os.getenv("MASTER_TOKEN")
    if master_token:
        known_tokens.add(master_token)

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

app.include_router(auth_router)
app.include_router(cal_router)
app.include_router(stripe_router)