import logfire
import requests
from devtools import debug
from fastapi import APIRouter, Request, HTTPException
from googleapiclient.errors import HttpError

from app.cal._utils import app_logger
from app.cal.tasks import create_or_update_trip_from_event, create_or_update_event_from_trip
from app.models import Event

from firebase_functions.firestore_fn import (
    on_document_written,
    Event,
    Change,
    DocumentSnapshot,
)

cal_webhook_router = APIRouter()


@cal_webhook_router.post('/cal_webhook')
async def receive_webhook(request: Request, calendar_id: str):
    app_logger.info('Received webhook with calendar_id: %s', calendar_id)

    headers = request.headers
    app_logger.info(f'Received headers: {headers}')

    # Extract the data from the headers
    channel_id = headers.get('X-Goog-Channel-ID')
    channel_token = headers.get('X-Goog-Channel-Token')
    channel_expiration = headers.get('X-Goog-Channel-Expiration')
    resource_id = headers.get('X-Goog-Resource-ID')
    resource_uri = headers.get('X-Goog-Resource-URI')
    resource_state = headers.get('X-Goog-Resource-State')
    message_number = headers.get('X-Goog-Message-Number')

    # Log the extracted data
    app_logger.info(f'Channel ID: {channel_id}')
    app_logger.info(f'Channel Token: {channel_token}')
    app_logger.info(f'Channel Expiration: {channel_expiration}')
    app_logger.info(f'Resource ID: {resource_id}')
    app_logger.info(f'Resource URI: {resource_uri}')
    app_logger.info(f'Resource State: {resource_state}')
    app_logger.info(f'Message Number: {message_number}')

    if resource_uri:
        try:
            response = requests.get(resource_uri)
            app_logger.info('requesting resource_uri: %s', resource_uri)
            data = response.json()
        except Exception as e:
            app_logger.error(f'Error fetching resource: {e}')
            raise HTTPException(status_code=400, detail="Error fetching resource")

        try:
            event = Event(**data)
        except Exception as e:
            app_logger.error(f'Error creating Event: {e}')
            raise HTTPException(status_code=400, detail="Invalid event data")

        try:
            if calendar_id and event.id:
                app_logger.info('Creating or updating trip from event')
                create_or_update_trip_from_event(calendar_id, event)
            app_logger.info('Received event webhook')
        except Exception as e:
            app_logger.error(f'Error in create_or_update_trip_from_event: {e}')
            raise HTTPException(status_code=500, detail="Error processing event")


@on_document_written(document="trips/{tripId}")
def firestore_trigger(event: Event[Change[DocumentSnapshot]]) -> None:
    # Fetch the specific trip document
    trip_data = event.data.after.to_dict()

    # Call the create_or_update_event_from_trip function
    try:
        create_or_update_event_from_trip(trip_data['propertyRef'], trip_data['reference'])
    except HttpError as e:
        app_logger.error(f'Error creating event from trip: {e}')
        raise HTTPException(status_code=400, detail=str(e))
