from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.errors import HttpError

from app.auth.views import get_token
from app.cal._utils import app_logger
from app.cal.tasks import create_or_update_event_from_trip, initalise_trips_from_cal
from app.models import PropertyCal, TripCal

cal_router = APIRouter()

# Set Google Calendar ID
@cal_router.post('/set_google_calendar_id')
def set_google_calendar_id(data: PropertyCal, token: str = Depends(get_token)):
    try:
        initalise_trips_from_cal(data.property_ref, data.cal_id)
        return {'propertyRef': data.property_ref, 'message': 'Google Calendar ID successfully set'}
    except HttpError as e:
        app_logger.error(f'Error setting Google Calendar ID: {e}')
        raise HTTPException(status_code=400, detail=str(e))

# Event from Trip
@cal_router.post('/event_from_trip')
def event_from_trip(data: TripCal, token: str = Depends(get_token)):
    try:
        create_or_update_event_from_trip(data.cal_id, data.trip_ref)
        return {'tripRef': data.trip_ref, 'message': 'Event successfully created from trip'}
    except HttpError as e:
        app_logger.error(f'Error creating event from trip: {e}')
        raise HTTPException(status_code=400, detail=str(e))