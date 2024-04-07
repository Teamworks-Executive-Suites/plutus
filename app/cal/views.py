from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.errors import HttpError

from app.auth.views import get_token
from app.cal._utils import app_logger
from app.cal.tasks import initalize_trips_from_cal
from app.models import PropertyCal

cal_router = APIRouter()


# Set Google Calendar ID
@cal_router.post('/set_google_calendar_id')
def set_google_calendar_id(data: PropertyCal, token: str = Depends(get_token)):
    app_logger.info('Setting Google Calendar ID...')
    try:
        initalize_trips_from_cal(data.property_ref, data.cal_id)
        app_logger.info('Google Calendar ID successfully set.')
        return {'propertyRef': data.property_ref, 'message': 'Google Calendar ID successfully set'}
    except HttpError as e:
        app_logger.error('Error setting Google Calendar ID: %s', e)
        raise HTTPException(status_code=400, detail=str(e))
