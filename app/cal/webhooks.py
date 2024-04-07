from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_functions.firestore_fn import (
    Change,
    DocumentSnapshot,
    Event,
    on_document_written,
)
from googleapiclient.errors import HttpError

from app.auth.views import get_token
from app.cal._utils import app_logger
from app.cal.tasks import (
    create_or_update_event_from_trip,
    delete_calendar_watch_channel,
    renew_notification_channel,
    sync_calendar,
)
from app.models import DeleteWebhookChannel
from app.utils import settings

cal_webhook_router = APIRouter()


@cal_webhook_router.post('/cal_webhook')
async def receive_webhook(request: Request, calendar_id: str):
    app_logger.info('Received webhook with calendar_id: %s', calendar_id)

    headers = request.headers
    app_logger.info('Received headers: %s', headers)

    # Extract the data from the headers
    channel_id = headers.get('X-Goog-Channel-ID')
    channel_token = headers.get('X-Goog-Channel-Token')
    channel_expiration = headers.get('X-Goog-Channel-Expiration')
    resource_id = headers.get('X-Goog-Resource-ID')
    resource_uri = headers.get('X-Goog-Resource-URI')
    resource_state = headers.get('X-Goog-Resource-State')
    message_number = headers.get('X-Goog-Message-Number')

    # Log the extracted data
    app_logger.info('Received channel_id: %s', channel_id)
    app_logger.info('Received channel_token: %s', channel_token)
    app_logger.info('Received channel_expiration: %s', channel_expiration)
    app_logger.info('Received resource_id: %s', resource_id)
    app_logger.info('Received resource_uri: %s', resource_uri)
    app_logger.info('Received resource_state: %s', resource_state)
    app_logger.info('Received message_number: %s', message_number)

    # Check if the channel expiration is within 1 week
    if channel_expiration:
        expiration_time = datetime.strptime(channel_expiration, '%a, %d %b %Y %H:%M:%S %Z')  # Parse the date string
        now = datetime.utcnow()
        if expiration_time - now < timedelta(weeks=1):
            channel_address = settings.url + calendar_id
            # Renew the notification channel
            renew_notification_channel(calendar_id, channel_id, 'web_hook', channel_address)

    if resource_id:
        try:
            if '-' in calendar_id:
                property_ref = calendar_id.split('-')[0]
            else:
                property_ref = calendar_id

            sync_calendar(property_ref)
        except HttpError as e:
            app_logger.error('Error syncing calendar: %s', e)
            raise HTTPException(status_code=400, detail=str(e))


@cal_webhook_router.post('/delete_webhook_channel')
def delete_webhook_channel(data: DeleteWebhookChannel, token: str = Depends(get_token)):
    app_logger.info('Deleting webhook channel...')
    try:
        app_logger.info('Deleting channel: %s', data.id)
        # Delete the channel
        delete_calendar_watch_channel(data.id, data.resourceId)
        app_logger.info('Webhook channel successfully deleted.')
        return {'message': 'Webhook channel successfully deleted'}
    except HttpError as e:
        app_logger.error('Error deleting webhook channel: %s', e)
        raise HTTPException(status_code=400, detail=str(e))


@on_document_written(document='trips/{tripId}')
def firestore_trigger(event: Event[Change[DocumentSnapshot]]) -> None:
    # Fetch the specific trip document
    trip_data = event.data.after.to_dict()

    # Call the create_or_update_event_from_trip function
    try:
        create_or_update_event_from_trip(trip_data['propertyRef'], trip_data['reference'])
    except HttpError as e:
        app_logger.error('Error creating event from trip: %s', e)
        raise HTTPException(status_code=400, detail=str(e))
