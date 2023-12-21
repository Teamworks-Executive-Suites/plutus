from fastapi import APIRouter

cal_router = APIRouter()


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
