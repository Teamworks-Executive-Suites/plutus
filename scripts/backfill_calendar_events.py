"""
One-off script to backfill missing Google Calendar events for all properties.

For each property with an externalCalendar, finds all future trips without an eventId
and creates Google Calendar events for them.

Usage:
    cd /path/to/plutus
    python scripts/backfill_calendar_events.py [--dry-run]
"""

import sys
from datetime import datetime

from google.cloud.firestore_v1 import FieldFilter
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Add parent dir so we can import app modules
sys.path.insert(0, '.')
from app.firebase_setup import db
from app.utils import settings

creds = service_account.Credentials.from_service_account_info(
    settings.firebase_credentials, scopes=['https://www.googleapis.com/auth/calendar']
)
service = build('calendar', 'v3', credentials=creds)

DRY_RUN = '--dry-run' in sys.argv


def backfill_all_properties():
    now = datetime.utcnow()
    properties = db.collection('properties').stream()

    total_created = 0
    total_skipped = 0
    total_errors = 0

    for prop in properties:
        prop_data = prop.to_dict()
        calendar_id = prop_data.get('externalCalendar')
        prop_name = prop_data.get('propertyName', prop.id)

        if not calendar_id:
            print(f'  SKIP {prop_name} — no externalCalendar')
            continue

        print(f'\n=== {prop_name} (calendar: {calendar_id[:30]}...) ===')

        # Find future trips without eventId
        trips = (
            db.collection('trips')
            .where(filter=FieldFilter('propertyRef', '==', prop.reference))
            .where(filter=FieldFilter('isExternal', '==', False))
            .where(filter=FieldFilter('tripBeginDateTime', '>', now))
            .stream()
        )

        for trip in trips:
            trip_data = trip.to_dict()

            if 'eventId' in trip_data:
                total_skipped += 1
                continue

            # Get user name
            user_ref = trip_data.get('userRef')
            guest_name = 'Guest'
            if user_ref:
                user_doc = user_ref.get()
                if user_doc.exists:
                    guest_name = user_doc.to_dict().get('display_name', 'Guest')

            begin = trip_data['tripBeginDateTime']
            end = trip_data['tripEndDateTime']
            is_blocked = trip_data.get('isBlocked', False)

            if is_blocked:
                summary = 'Blocked | Teamworks'
            else:
                summary = f'Office Booking for {guest_name} | Teamworks'

            booking_link = f'{settings.app_url}/bookingDetails?tripPassed={trip.id}&property={prop.id}'

            event_body = {
                'summary': summary,
                'description': f'Property: {prop_name}\nTrip Ref: trips/{trip.id}\nBooking Link: {booking_link}',
                'start': {'dateTime': begin.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': end.isoformat(), 'timeZone': 'UTC'},
            }

            print(f'  {trip.id}: {summary} | {begin.strftime("%b %d %H:%M")}-{end.strftime("%H:%M")} UTC', end='')

            if DRY_RUN:
                print(' [DRY RUN — would create]')
                total_created += 1
                continue

            try:
                event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
                trip.reference.update({'eventId': event['id']})
                print(f' -> created {event["id"]}')
                total_created += 1
            except HttpError as e:
                print(f' -> ERROR: {e}')
                total_errors += 1

    print(f'\n--- Summary ---')
    print(f'Created: {total_created}')
    print(f'Skipped (already had eventId): {total_skipped}')
    print(f'Errors: {total_errors}')
    if DRY_RUN:
        print('(DRY RUN — no actual changes made)')


if __name__ == '__main__':
    backfill_all_properties()
