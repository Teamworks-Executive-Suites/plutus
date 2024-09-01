from datetime import datetime, timedelta

import logfire
from devtools import debug
from fastapi import HTTPException
from googleapiclient.errors import HttpError

from app.auto._utils import app_logger
from app.cal.tasks import delete_calendar_watch_channel, initalize_trips_from_cal, sync_calendar_events
from app.firebase_setup import db
from app.models import PropertyCal


def auto_check_and_renew_channels():
    with logfire.span('auto_check_and_renew_channels'):
        # Get the current time
        now = datetime.utcnow()

        # Iterate over all property documents
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            # Get the channel expiration time
            try:
                channel_expiration = prop.get('channelExpiration')
            except KeyError:
                app_logger.info('Channel expiration time not found for property: %s', prop.id)
                continue

            # If the channel is about to expire, renew it
            if channel_expiration and datetime.fromtimestamp(int(channel_expiration) / 1000) - now < timedelta(days=2):
                app_logger.info('Renewing channel for property: %s', prop.id)
                try:
                    # Assuming `data` is a dictionary or object with required properties
                    data = {
                        'property_ref': prop.reference,
                        'cal_id': prop.get('calId')  # Assuming calId is stored in the property document
                    }
                    initalize_trips_from_cal(data['property_ref'], data['cal_id'])
                    app_logger.info('Google Calendar ID successfully set.')
                except HttpError as e:
                    error_message = str(e)
                    app_logger.error('Error setting Google Calendar ID: %s', error_message)
                    if 'not unique' in error_message:
                        with logfire.span('Channel id not unique'):
                            app_logger.info('Channel id not unique error encountered. Deleting the channel...')
                            calendar_resource_id = 'zaI1vco_ZDFf7n_oBTclPGvx6Zk'  # Hardcoded resource id
                            delete_calendar_watch_channel(data['property_ref'], calendar_resource_id)
                            app_logger.info('Channel successfully deleted.')
                            app_logger.info('Retrying to set Google Calendar ID...')
                            initalize_trips_from_cal(data['property_ref'], data['cal_id'])
                            app_logger.info('Google Calendar ID successfully set.')
                    raise HTTPException(status_code=400, detail=error_message)

                # Assuming `new_channel` and `expiration` are obtained from the response of `initalize_trips_from_cal`
                new_channel = {
                    'id': 'new_channel_id',  # Replace with actual new channel id
                    'expiration': int((now + timedelta(days=30)).timestamp() * 1000)  # Example expiration time
                }
                prop.reference.update({'channelId': new_channel['id'], 'channelExpiration': new_channel['expiration']})

                app_logger.info('Channel for property: %s successfully renewed', prop.id)
            else:
                app_logger.info('Channel for property: %s does not need to be renewed', prop.id)


def resync_all_calendar_events():
    """
    Resync all calendar events for all
    """
    with logfire.span('resync_all_calendar_events'):
        # Iterate over all property documents
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            try:
                sync_calendar_events(prop.reference)
            except Exception as e:
                app_logger.error('Error syncing calendar events for property: %s', prop.id)
                app_logger.error(e)
                continue
            app_logger.info('Calendar events for property: %s successfully synced', prop.id)

        app_logger.info('All calendar events successfully synced')
