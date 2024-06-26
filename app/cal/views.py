import logfire
from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.errors import HttpError

from app.auth.views import get_token
from app.cal._utils import app_logger
from app.cal.tasks import (
    create_or_update_event_from_trip,
    delete_calendar_watch_channel,
    delete_event_from_trip,
    initalize_trips_from_cal,
)
from app.models import EventFromTrip, PropertyCal

cal_router = APIRouter()


# Set Google Calendar ID
@cal_router.post('/set_google_calendar_id')
def set_google_calendar_id(data: PropertyCal, token: str = Depends(get_token)):
    app_logger.info('Setting Google Calendar ID for property: %s', data.property_ref)
    try:
        initalize_trips_from_cal(data.property_ref, data.cal_id)
        app_logger.info('Google Calendar ID successfully set.')
        return {'propertyRef': data.property_ref, 'message': 'Google Calendar ID successfully set'}
    except HttpError as e:
        error_message = str(e)
        app_logger.error('Error setting Google Calendar ID: %s', error_message)
        if 'not unique' in error_message:
            with logfire.span('Channel id not unique'):
                app_logger.info('Channel id not unique error encountered. Deleting the channel...')
                calendar_resource_id = 'zaI1vco_ZDFf7n_oBTclPGvx6Zk'  # Hardcoded resource id
                delete_calendar_watch_channel(data.property_ref, calendar_resource_id)
                app_logger.info('Channel successfully deleted.')
                app_logger.info('Retrying to set Google Calendar ID...')
                initalize_trips_from_cal(data.property_ref, data.cal_id)
                app_logger.info('Google Calendar ID successfully set.')
        raise HTTPException(status_code=400, detail=error_message)


@cal_router.post('/event_from_trip')
def process_create_or_update_event_from_trip(data: EventFromTrip, token: str = Depends(get_token)):
    app_logger.info(
        'Process creating or updating event for trip: %s, with property_ref: %s', data.trip_ref, data.property_ref
    )
    # Call the create_or_update_event_from_trip function
    try:
        create_or_update_event_from_trip(data.property_ref, data.trip_ref)
        return {
            'tripRef': data.trip_ref,
            'propertyRef': data.property_ref,
            'message': 'Event successfully created or updated',
        }
    except Exception as e:
        app_logger.error('Error creating event from trip: %s', e)
        raise HTTPException(status_code=400, detail=str(e))


# Delete Event from Trip
@cal_router.post('/delete_event_from_trip')
def process_delete_event_from_trip(data: EventFromTrip, token: str = Depends(get_token)):
    app_logger.info('Process deleting event for trip: %s, with property_ref: %s', data.trip_ref, data.property_ref)
    # Call the create_or_update_event_from_trip function
    try:
        delete_event_from_trip(data.property_ref, data.trip_ref)
        return {'tripRef': data.trip_ref, 'propertyRef': data.property_ref, 'message': 'Event successfully deleted'}
    except Exception as e:
        app_logger.error('Error deleting event from trip: %s', e)
        raise HTTPException(status_code=400, detail=str(e))
