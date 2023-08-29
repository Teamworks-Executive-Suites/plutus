import time
import typing as t

import schedule
from devtools import debug
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.responses import FileResponse

from models import *
from tasks import *

app = FastAPI()

# Auth

# gets the bearer token from the file for verification
known_tokens = set()
with open("bearer_token.txt", "r") as import_file:
    bearer_token = import_file.read().strip()
known_tokens.add(bearer_token)

# We will handle a missing token ourselves
get_bearer_token = HTTPBearer(auto_error=False)


async def get_token(
        auth: t.Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
) -> str:
    # Simulate a database query to find a known token
    if auth is None or (token := auth.credentials) not in known_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UnauthorizedMessage().detail,
        )
    return token


@app.on_event("startup")
def startup_event():
    schedule.every().hour.do(update_calendars)

    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(3600)

    import threading
    threading.Thread(target=run_schedule).start()


# Endpoints
# Stripe

@app.post("/refund_deposit")
def refund(data: Dispute,
           token: str = Depends(get_token)):
    return get_dispute_from_firebase(data.trip_ref)



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
    debug(data.property_ref)
    debug(data.cal_link)
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
