from datetime import datetime, timedelta

import logfire

from app.auto._utils import app_logger
from app.cal.tasks import renew_notification_channel
from app.firebase_setup import db
from app.utils import settings


def check_and_renew_channels():
    with logfire.span('Check and renew notification channels'):
        # Get the current time
        now = datetime.utcnow()

        # Iterate over all property documents
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            # Get the channel expiration time
            try:
                channel_expiration = prop.get('channelExpiration')
            except KeyError:
                app_logger.error('Channel expiration time not found for property: %s', prop.id)
                continue

            # If the channel is about to expire, renew it
            if channel_expiration and datetime.fromtimestamp(int(channel_expiration) / 1000) - now < timedelta(days=2):
                app_logger.info('Renewing channel for property: %s', prop.id)
                calendar_id = prop.get('externalCalendar')
                channel_id = prop.get('channelId')
                channel_address = settings.url + calendar_id
                try:
                    new_channel, expiration = renew_notification_channel(calendar_id, channel_id, 'web_hook', channel_address)
                except Exception as e:
                    app_logger.error('Error renewing channel for property: %s', prop.id)
                    app_logger.error(e)
                    continue

                # Update the property document with the new channel id and expiration time
                prop.reference.update({'channelId': new_channel['id'], 'channelExpiration': expiration})

                app_logger.info('Channel for property: %s successfully renewed', prop.id)
            else:
                app_logger.info('Channel for property: %s does not need to be renewed', prop.id)