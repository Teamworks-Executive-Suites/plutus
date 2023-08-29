import time

import schedule
from fastapi import FastAPI
from starlette.responses import FileResponse

from models import *
from tasks import *
from devtools import debug
app = FastAPI()

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

@app.post('/refund_deposit')

def refund(data: Dispute):
    return get_dispute_from_firebase(data.trip_ref)



# Calendar Generation
@app.get('/get_property_cal')
def get_property_cal(property_ref: str):
    cal_link = create_cal_for_property(property_ref)
    # add all cal stuff
    debug("test")

    return {
        "propertyRef": property_ref,
        "cal_link": cal_link
    }

# Sync External Calendar
@app.post('/cal_to_property')
def cal_to_property(data: PropertyCal):
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
