import logfire
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
    try:
        body = await request.body()
        if not body:
            app_logger.error('Empty request body')
            raise HTTPException(status_code=400, detail="Empty request body")
        data = await request.json()
    except Exception as e:
        app_logger.error(f'Error parsing JSON: {e}')
        raise HTTPException(status_code=400, detail="Invalid JSON")

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
