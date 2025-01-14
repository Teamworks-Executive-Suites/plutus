from datetime import datetime, timedelta

import logfire
from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.errors import HttpError

from app.auth.views import get_token
from app.cal._utils import app_logger
from app.cal.tasks import (
    create_or_update_event_from_trip,
    delete_calendar_watch_channel,
    delete_event_from_trip,
    initialize_trips_from_cal,
)
from app.firebase_setup import db
from app.models import EventFromTrip, PropertyCal, PropertyRef
from app.utils import settings

cal_router = APIRouter()


# Set Google Calendar ID
@cal_router.post('/set_google_calendar_id')
def set_google_calendar_id(data: PropertyCal, token: str = Depends(get_token)):
    app_logger.info('Setting Google Calendar ID for property: %s', data.property_ref)
    try:
        initialize_trips_from_cal(data.property_ref, data.cal_id)
        app_logger.info('Google Calendar ID successfully set.')
        return {'propertyRef': data.property_ref, 'message': 'Google Calendar ID successfully set'}
    except HttpError as e:
        error_message = str(e)
        app_logger.error('Error setting Google Calendar ID: %s', error_message)
        if 'not unique' in error_message:
            with logfire.span('Channel id not unique'):
                app_logger.info('Channel id not unique error encountered. Deleting the channel...')
                delete_calendar_watch_channel(data.property_ref, settings.g_calendar_resource_id)
                app_logger.info('Channel successfully deleted.')
                app_logger.info('Retrying to set Google Calendar ID...')
                initialize_trips_from_cal(data.property_ref, data.cal_id)
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


@cal_router.post('/resync_property_calendar_events')
def process_resync_property_calendar_events(data: PropertyRef, token: str = Depends(get_token)):
    with logfire.span('resync_property_calendar_events'):
        app_logger.info('Resyncing calendar events for property: %s', data.property_ref)

        # get the calendar id from the property reference
        property_doc = db.collection('properties').document(data.property_ref).get()
        cal_id = property_doc.get('externalCalendar')

        if not cal_id:
            app_logger.error('Calendar ID not found for property: %s', data.property_ref)
            raise HTTPException(status_code=400, detail='Calendar ID not found for property')

        app_logger.info('Renewing channel for property: %s', data.property_ref)
        try:
            external_calendar = property_doc.get('externalCalendar')
            if not external_calendar:
                app_logger.info('externalCalendar not found for property: %s', data.property_ref)
                return

            property_ref = 'properties/' + data.property_ref
            property_cal = PropertyCal(property_ref=property_ref, cal_id=external_calendar)

            initialize_trips_from_cal(property_cal.property_ref, property_cal.cal_id)
            app_logger.info('Google Calendar ID successfully set.')

        except HttpError as e:
            error_message = str(e)
            app_logger.error('Error setting Google Calendar ID: %s', error_message)
            if 'not unique' in error_message:
                with logfire.span('Channel id not unique'):
                    delete_calendar_watch_channel(property_cal.property_ref, settings.g_calendar_resource_id)
                    initialize_trips_from_cal(property_cal.property_ref, property_cal.cal_id)
            raise HTTPException(status_code=400, detail=error_message)

        new_channel = {
            'id': 'new_channel_id',
            'expiration': int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000),
        }
        property_doc.reference.update(
            {'channelId': new_channel['id'], 'channelExpiration': str(new_channel['expiration'])}
        )
