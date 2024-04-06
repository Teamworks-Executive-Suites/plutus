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

cal_router = APIRouter()


@cal_router.post('/cal_webhook')
async def receive_webhook(request: Request, calendar_id: str):
    data = await request.json()
    if data.get('kind') != 'calendar#event':
        app_logger.info('Received non-event webhook')
    event = Event(**data)
    if calendar_id and event.id:
        create_or_update_trip_from_event(calendar_id, event)
    app_logger.info('Received event webhook')


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
