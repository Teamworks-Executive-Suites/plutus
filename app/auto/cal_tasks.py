from datetime import datetime, timedelta

import logfire

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
            channel_expiration = prop.get('channelExpiration')

            # If the channel is about to expire, renew it
            if channel_expiration and datetime.fromtimestamp(channel_expiration / 1000) - now < timedelta(days=2):
                calendar_id = prop.get('externalCalendar')
                channel_id = prop.get('channelId')
                channel_address = settings.url + calendar_id
                new_channel, expiration = renew_notification_channel(calendar_id, channel_id, 'web_hook', channel_address)

                # Update the property document with the new channel id and expiration time
                prop.reference.update({'channelId': new_channel['id'], 'channelExpiration': expiration})