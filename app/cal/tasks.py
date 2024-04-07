import uuid
from datetime import datetime, timedelta

import logfire
from fastapi import HTTPException
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.cal._utils import app_logger
from app.firebase_setup import db
from app.models import TripData
from app.utils import settings

creds = service_account.Credentials.from_service_account_info(
    settings.firebase_credentials, scopes=['https://www.googleapis.com/auth/calendar']
)


def renew_notification_channel(calendar_id, channel_id, channel_type, channel_address):
    service = build('calendar', 'v3', credentials=creds)

    # Fetch the current notification channel
    channel = service.events().watch(calendarId=calendar_id, body={
        'id': channel_id,
        'type': channel_type,
        'address': channel_address
    }).execute()

    # Get the current time and the expiration time of the channel
    now = datetime.utcnow()
    expiration_time = datetime.fromtimestamp(int(channel['expiration']) / 1000)  # Convert from milliseconds to seconds

    # If the channel is close to its expiration (e.g., within 24 hours), renew it
    if expiration_time - now < timedelta(hours=24):
        # Create a new channel with a unique id
        new_channel_id = channel_id + '-renewed' + str(uuid.uuid4())
        new_channel = service.events().watch(calendarId=calendar_id, body={
            'id': new_channel_id,
            'type': channel_type,
            'address': channel_address
        }).execute()

        print(f'Renewed notification channel. Old id: {channel_id}, new id: {new_channel_id}')

        return new_channel


def sync_calendar(property_ref):
    app_logger.info('Syncing calendar for property: %s', property_ref)

    # Fetch the specific property document
    collection_id, document_id = property_ref.split('/')
    property_doc_ref = db.collection(collection_id).document(document_id)

    # Fetch the property document
    property_doc = property_doc_ref.get()
    if not property_doc.exists:
        app_logger.error('Property document does not exist for: %s', property_ref)
        raise HTTPException(status_code=400, detail='Property not found')

    # Convert the DocumentSnapshot to a dictionary
    property_doc_dict = property_doc.to_dict()

    calendar_id = property_doc_dict.get('externalCalendar')
    next_sync_token = property_doc_dict.get('nextSyncToken')

    # If nextSyncToken does not exist in the document, assign a default value
    if next_sync_token is None:
        app_logger.info('nextSyncToken does not exist')
        next_sync_token = ''

    # Call the Google Calendar API to fetch the events
    service = build('calendar', 'v3', credentials=creds)
    try:
        with logfire.span('fetching events from calendar'):
            page_token = None
            while True:
                events_result = (
                    service.events()
                    .list(calendarId=calendar_id, syncToken=next_sync_token, pageToken=page_token)
                    .execute()
                )
                events = events_result.get('items', [])

                # Get the current time
                now = datetime.utcnow()
                # Query for all documents where 'propertyRef' matches the given property_ref, 'isExternal' is True,
                # and 'tripBeginDateTime' is in the future
                all_external_trips = (
                    db.collection('trips')
                    .where('propertyRef', '==', property_ref)
                    .where('isExternal', '==', True)
                    .where('tripBeginDateTime', '>', now)
                    .stream()
                )
                all_external_trip_ids = [trip.to_dict()['eventId'] for trip in all_external_trips]

                # For each event, create or update a trip document
                for event in events:
                    # Convert the event data to Firestore trip format
                    trip_data = TripData(
                        isExternal=True,
                        propertyRef=property_ref,
                        # Add a buffer time of 30 minutes to tripBeginDateTime and tripEndDateTime
                        tripBeginDateTime=datetime.fromisoformat(event['start'].get('dateTime')) - timedelta(
                            minutes=30),
                        tripEndDateTime=datetime.fromisoformat(event['end'].get('dateTime')) + timedelta(minutes=30),
                        eventId=event['id'],  # Save the event ID on the trip
                    )

                    # Convert the trip_data to a dictionary
                    trip_data_dict = trip_data.dict()

                    # Check if a trip with the same eventId already exists
                    existing_trip_ref = db.collection('trips').where('eventId', '==', event['id']).get()
                    if existing_trip_ref:
                        # If a trip with the same eventId exists, update it
                        existing_trip_ref[0].reference.update(trip_data_dict)
                        app_logger.info('Updated trip from event: %s', event['id'])
                    else:
                        # If no trip with the same eventId exists, create a new one
                        new_trip_ref = db.collection('trips').add(trip_data_dict)
                        app_logger.info('Added trip from event: %s, new trip ref: %s', event['id'], new_trip_ref[1].id)

                # Check for deleted events
                for trip_id in all_external_trip_ids:
                    if trip_id not in [event['id'] for event in events]:
                        # If a trip exists in the database that does not have a corresponding event in the Google
                        # Calendar, delete that trip
                        deleted_trip_ref = db.collection('trips').document(trip_id).delete()
                        app_logger.info('Deleted trip with id: %s, trip deleted ref: %s', trip_id, deleted_trip_ref[1].id)

                # Store the nextSyncToken from the response
                next_sync_token = events_result.get('nextSyncToken')

                # Save the nextSyncToken to use in the next sync request
                # Update the property document with the new sync token
                property_doc_ref.update({'nextSyncToken': next_sync_token})

                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break

    except HttpError as e:
        if e.resp.status == 410:
            # A 410 status code, "Gone", indicates that the sync token is invalid.
            app_logger.info('Invalid sync token, clearing event store and re-syncing.')
            clear_event_store()
            sync_calendar(property_ref)
        else:
            app_logger.error('Error syncing calendar: %s', e)
            raise HTTPException(status_code=400, detail=str(e))


def clear_event_store(property_ref):
    # Get a reference to the 'trips' collection
    trips_ref = db.collection('trips')

    # Get the current time
    now = datetime.utcnow()

    # Query for all documents where 'propertyRef' matches the given property_ref, 'isExternal' is True,
    # and 'tripBeginDateTime' is in the future
    docs = (
        trips_ref.where('propertyRef', '==', property_ref)
        .where('isExternal', '==', True)
        .where('tripBeginDateTime', '>', now)
        .stream()
    )

    # Delete each document
    for doc in docs:
        doc.reference.delete()

    app_logger.info('Event store successfully cleared.')


def delete_calendar_watch_channel(id, resource_id):
    app_logger.info('Deleting calendar watch channel: %s', id)
    # Call the Google Calendar API to delete the channel
    service = build('calendar', 'v3', credentials=creds)
    try:
        service.channels().stop(body={'id': id, 'resourceId': resource_id}).execute()
        app_logger.info('Calendar watch channel successfully deleted.')
    except HttpError as e:
        app_logger.error('Error deleting calendar watch channel: %s', e)
        raise HTTPException(status_code=400, detail=str(e))


def create_or_update_trip_from_event(calendar_id, event):
    app_logger.info('Creating or updating trip from event: %s', event['id'])
    # Convert the event data to Firestore trip format
    trip_data = TripData(
        isExternal=True,
        propertyRef=calendar_id,
        tripBeginDateTime=datetime.fromisoformat(event['start'].get('dateTime')),
        tripEndDateTime=datetime.fromisoformat(event['end'].get('dateTime')),
        eventId=event['id'],  # Save the event ID on the trip
    )

    # Fetch the specific trip document associated with the event id
    trip_ref = db.collection('trips').document(event['id']).get()
    if trip_ref.exists:
        app_logger.info('Trip document exists for event: %s', trip_ref.id)
        # The trip document exists, so update it
        trip_ref.update(trip_data)
    else:
        app_logger.info('Trip document does not exist for event, so we create it: %s', event['id'])
        # The trip document does not exist, so create it
        db.collection('trips').add(trip_data)


def initalize_trips_from_cal(property_ref, calendar_id):
    app_logger.info('Initialising trips from calendar: %s , property: %s', calendar_id, property_ref)

    # get the property document
    collection_id, document_id = property_ref.split('/')
    property_doc_ref = db.collection(collection_id).document(document_id)

    # Call the Google Calendar API to fetch the future events
    service = build('calendar', 'v3', credentials=creds)

    # test calendar list
    calendars = service.calendarList().list().execute()
    for calendar_list_entry in calendars['items']:
        app_logger.info(calendar_list_entry['id'], calendar_list_entry['summary'])

    # Set up the webhook
    with logfire.span('setting up webhook for calendar'):
        channel_id = str(uuid.uuid4())
        app_logger.info('Setting up webhook and setting the channel_id: %s', property_ref)
        webhook_url = f'{settings.url}/cal_webhook?calendar_id={property_ref}'
        channel = (
            service.events()
            .watch(calendarId=calendar_id, body={'id': channel_id, 'type': 'web_hook', 'address': webhook_url})
            .execute()
        )

        property_doc_ref.update({'channelId': channel['resourceId']})

    sync_calendar(property_ref)


def create_or_update_event_from_trip(property_ref, trip_ref):
    app_logger.info('Creating or updating event from trip: %s , property: %s', trip_ref, property_ref)
    # Fetch the specific property document

    collection_id, document_id = property_ref.split('/')
    property_doc = db.collection(collection_id).document(document_id).get()

    if property_doc.exists:
        app_logger.info('Property document exists for trip: %s', property_ref)
        property_data = property_doc.to_dict()
        calendar_id = property_data['externalCalendar']
        property_name = property_data['propertyName']  # Fetch the property name

        # Fetch the specific trip document
        collection_id, document_id = trip_ref.split('/')
        trip_doc = db.collection(collection_id).document(document_id).get()
        if trip_doc.exists:
            trip_data = trip_doc.to_dict()

            # Fetch the specific user document
            collection_id, document_id = trip_data['userRef'].split('/')
            user_doc = db.collection(collection_id).document(document_id).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                guest_name = user_data['displayName']

                # Construct the booking link
                booking_link = (
                    f'https://app.bookteamworks.com/tripDetails?tripPassed={trip_ref}&property={property_ref}'
                )

                # Convert the trip data to Google Calendar event format
                # Add 30-minute buffer time to either side of the event
                event_data = {
                    'id': trip_data['eventId'],
                    'summary': f'TW - Office Booking for {guest_name}',  # Generate the event name
                    'description': f'Property: {property_name}\nTrip Ref: {trip_ref}\nBooking Link: {booking_link}',
                    # Add the event description
                    'start': {
                        'dateTime': (trip_data['tripBeginDateTime'] - timedelta(minutes=30)).isoformat(),
                        'timeZone': 'UTC',
                    },
                    'end': {
                        'dateTime': (trip_data['tripEndDateTime'] + timedelta(minutes=30)).isoformat(),
                        'timeZone': 'UTC',
                    },
                }

                # Call the Google Calendar API to update or create the event
                service = build('calendar', 'v3', credentials=creds)
                if 'eventId' in trip_data:
                    app_logger.info('Updating event: %s', trip_data['eventId'])
                    service.events().update(
                        calendarId=calendar_id, eventId=trip_data['eventId'], body=event_data
                    ).execute()
                else:
                    app_logger.info('Creating a new event')
                    service.events().insert(calendarId=calendar_id, body=event_data).execute()

            else:
                app_logger.error('User document does not exist for: %s', trip_data['userRef'])
                raise HttpError
        else:
            app_logger.error('Trip document does not exist for: %s', trip_ref)
            raise HttpError
    else:
        app_logger.error('Property document does not exist for: %s', property_ref)
        raise HttpError
