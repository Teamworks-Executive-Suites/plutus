from fastapi import FastAPI
from starlette.responses import FileResponse

from models import *
from tasks import *
from devtools import debug
app = FastAPI()

# Nica was here

@app.get('/')
def hello():
    return {"hello world": "this worked!"}

@app.post('/edit')
def test_post(name: Name):
    return{ "message": f'hello {name} this test worked'}

@app.post('/refund_deposit')
def refund(ref: Dispute):
   # get dispute document from firebase where ref == ref
    # get user document from firebase where user == user
    get_dispute_from_firebase(ref)

    return{"message": f'hello {ref} this test worked'}


@app.get('/get_property_cal')
def get_property_cal(property_ref: str):
    cal_link = create_cal_for_property(property_ref)
    # add all cal stuff
    debug("test")

    return {
        "propertyRef": property_ref,
        "cal_link": cal_link
    }

@app.post('/cal_to_property')
def cal_to_property(data: PropertyCal):
    debug(data.property_ref)
    debug(data.cal_link)
    debug(data.external_source)
    # add all cal stuff
    if create_trips_from_ics(data.property_ref, data.cal_link, data.external_source):
        return {
            "propertyRef": data.property_ref,
            "message": "Calendar successfully added to property"
        }
    else:
        return {
            "propertyRef": data.property_ref,
            "message": "Calendar could not be added to property"
        }




# Serve the .ics file using FastAPI's static files
ics_directory = "./calendars"  # Replace with your directory path
app.mount("/calendars", FileResponse(ics_directory))