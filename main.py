import typing as t
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.responses import FileResponse
from bearer_token import *
from models import *
from tasks import *

from settings import Settings

settings = Settings()

app = FastAPI()


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

# Auth
generate_bearer_token()
# gets the bearer token from the file for verification
known_tokens = set()
with open("bearer_token.txt", "r") as import_file:
    btoken = import_file.read().strip()
known_tokens.add(btoken)

# We will handle a missing token ourselves
get_bearer_token = HTTPBearer(auto_error=False)


async def get_token(
        auth: t.Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    # If settings.testing is True, return a dummy token
    debug(settings.testing)
    if settings.test_token:
        known_tokens.add(settings.test_token)

    # Simulate a database query to find a known token
    debug(known_tokens)
    if auth is None or (token := auth.credentials) not in known_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UnauthorizedMessage().detail,
            # Assuming UnauthorizedMessage is defined somewhere in your actual code
        )
    return token


# Endpoints
# Stripe


@app.post("/extra_charge")
def extra_charge(data: Trip, token: str = Depends(get_token)):
    return process_extra_charge(data.trip_ref)


@app.post("/refund")
def refund(data: Refund, token: str = Depends(get_token)):
    debug(data)
    print('reeeee')
    return handle_refund(data.trip_ref, data.amount)


@app.post("/cancel_refund")
def cancel_refund(data: Trip, token: str = Depends(get_token)):
    return process_cancel_refund(data.trip_ref)


# Calendar Generation
@app.get('/get_property_cal')
def get_property_cal(property_ref: str, token: str = Depends(get_token)):
    cal_link = create_cal_for_property(property_ref)
    # add all cal stuff
    return {
        "propertyRef": property_ref,
        "cal_link": cal_link
    }


# Sync External Calendar
@app.post('/cal_to_property')
def cal_to_property(data: PropertyCal, token: str = Depends(get_token)):
    logging.info(data.property_ref)
    logging.info(data.cal_link)
    # add all cal stuff
    if create_trips_from_ics(data.property_ref, data.cal_link):
        return {
            "propertyRef": data.property_ref,
            "message": "Calendar successfully added to property"
        }
    else:
        return {
            "propertyRef": data.property_ref,
            "message": "Calendar could not be added to property"
        }


# Static Files

ics_directory = "./calendars"  # Replace with your directory path
app.mount("/calendars", FileResponse(ics_directory))
