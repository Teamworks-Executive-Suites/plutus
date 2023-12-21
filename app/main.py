from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from tasks2 import *

from app.settings import Settings
from app.auth.views import auth_router
from app.calendar.views import cal_router
from app.stripe.views import stripe_router
from app.static.views import static_router

settings = Settings()

app = FastAPI()

known_tokens = set()
@app.on_event("startup")
async def startup_event():
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

app.include_router(auth_router)
app.include_router(cal_router)
app.include_router(stripe_router)
app.include_router(static_router)