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
        app_logger.info('Starting auto_check_and_renew_channels job')
        debug('Starting auto_check_and_renew_channels job')
        # Iterate over all property documents
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            debug(prop)
            app_logger.info('Renewing channel for property: %s', prop.id)

            # Check if 'externalCalendar' exists in the property document
            if 'externalCalendar' not in prop.to_dict():
                app_logger.warning('Property %s does not contain externalCalendar', prop.id)
                continue

            calendar_id = prop.get('externalCalendar')

            # Create a PropertyCal object
            data = PropertyCal(property_ref=prop.id, cal_id=calendar_id)

            try:
                # Call set_google_calendar_id programmatically
                app_logger.info('Setting Google Calendar ID for property: %s', data.property_ref)
                try:
                    initalize_trips_from_cal(data.property_ref, data.cal_id)
                    app_logger.info('Channel for property: %s successfully renewed', prop.id)
                    debug('Channel for property: %s successfully renewed', prop.id)
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
            except Exception as e:
                app_logger.error('Error renewing channel for property: %s', prop.id)
                app_logger.error(e)
                continue
        app_logger.info('Completed auto_check_and_renew_channels job')


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
