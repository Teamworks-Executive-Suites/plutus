from datetime import datetime, timedelta

import logfire
from fastapi import HTTPException
from googleapiclient.errors import HttpError

from app.auto._utils import app_logger
from app.cal.tasks import delete_calendar_watch_channel, initialize_trips_from_cal, sync_calendar_events
from app.firebase_setup import db
from app.models import PropertyCal
from app.utils import settings


def auto_check_and_renew_channels(force_renew=False):
    with logfire.span('auto_check_and_renew_channels; force renew: %s', force_renew):
        now = datetime.utcnow()
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            app_logger.info('Checking property: %s', prop.id)

            channel_expiration = prop.get('channelExpiration', None)
            if channel_expiration is None:
                app_logger.info('Channel expiration time not found for property: %s', prop.id)
                continue

            if force_renew or (
                channel_expiration and datetime.fromtimestamp(int(channel_expiration) / 1000) - now < timedelta(days=2)
            ):
                app_logger.info('Renewing channel for property: %s', prop.id)
                try:
                    external_calendar = prop.get('externalCalendar')
                    if not external_calendar:
                        app_logger.info('externalCalendar not found for property: %s', prop.id)
                        continue

                    property_ref = 'properties/' + prop.id
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
                    'expiration': int((now + timedelta(days=30)).timestamp() * 1000),
                }
                prop.reference.update(
                    {'channelId': new_channel['id'], 'channelExpiration': str(new_channel['expiration'])}
                )

            else:
                app_logger.info('Channel for property: %s does not need to be renewed', prop.id)
    app_logger.info('Finished auto_check_and_renew_channels')


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
