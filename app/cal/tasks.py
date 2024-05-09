import uuid
from datetime import datetime, timedelta
from typing import Any, Union

import logfire
from fastapi import HTTPException
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import ValidationError

from app.cal._utils import app_logger
from app.firebase_setup import db
from app.models import CancelledGCalEvent, GCalEvent, TripData
from app.utils import settings

creds = service_account.Credentials.from_service_account_info(
    settings.firebase_credentials, scopes=['https://www.googleapis.com/auth/calendar']
)


def renew_notification_channel(calendar_id, channel_id, channel_type, channel_address):
    service = build('calendar', 'v3', credentials=creds)

    # Create a new channel with a unique id
    new_channel_id = str(uuid.uuid4())
    new_channel = (
        service.events()
        .watch(calendarId=calendar_id, body={'id': new_channel_id, 'type': channel_type, 'address': channel_address})
        .execute()
    )

    app_logger.info('Renewed notification channel. Old id: %s, new id: %s', channel_id, new_channel['id'])

    return new_channel


def sync_calendar_events(property_doc_ref: Any):
    app_logger.info(f'Syncing calendar for property: {property_doc_ref}')

    # Fetch the specific property document
    # collection_id, document_id = property_ref.split('/')
    # property_doc_ref = db.collection(collection_id).document(document_id)

    if isinstance(property_doc_ref, str):
        property_doc_ref = db.document(property_doc_ref)

    property_doc = property_doc_ref.get()

    if not property_doc.exists:
        app_logger.error('Property document does not exist for: %s', property_doc_ref)
        raise HTTPException(status_code=404, detail='Property not found')

    property_doc_dict = property_doc.to_dict()
    calendar_id = property_doc_dict.get('externalCalendar')
    next_sync_token = property_doc_dict.get('nextSyncToken', '')

    # Call the Google Calendar API to fetch the events
    service = build('calendar', 'v3', credentials=creds)
    page_token = None

    try:
        while True:
            events_result = (
                service.events().list(calendarId=calendar_id, syncToken=next_sync_token, pageToken=page_token).execute()
            )

            events = events_result.get('items', [])
            for event in events:
                try:
                    # Validate the event data with the appropriate model
                    if event['status'] == 'cancelled':
                        validated_event = CancelledGCalEvent.parse_obj(event)
                    else:
                        validated_event = GCalEvent.parse_obj(event)
                except ValidationError as ve:
                    app_logger.error('Event validation error: %s, Event: %s', ve, event['id'])
                    continue

                # Process each event
                process_event(validated_event, property_doc_ref)

            next_sync_token = events_result.get('nextSyncToken')
            property_doc_ref.update({'nextSyncToken': next_sync_token})

            page_token = events_result.get('nextPageToken')
            if not page_token:
                break
    except HttpError as e:
        if e.resp.status == 410:
            app_logger.info('Invalid sync token, clearing event store and re-syncing.')
            clear_event_store(property_doc_ref.path)
            sync_calendar_events(property_doc_ref)
        else:
            app_logger.error('Error syncing calendar: %s', e)
            raise HTTPException(status_code=500, detail=str(e))


def convert_event_to_trip_data(event: GCalEvent, property_doc_ref: Any) -> TripData:
    start_datetime_str = event.start.dateTime
    end_datetime_str = event.end.dateTime

    # Parse the start and end datetime strings from the event
    start_datetime = datetime.fromisoformat(start_datetime_str) if start_datetime_str else None
    end_datetime = datetime.fromisoformat(end_datetime_str) if end_datetime_str else None

    if not start_datetime or not end_datetime:
        raise ValueError('Event start or end datetime is missing')

    # Adding a buffer of 30 minutes before the trip start and after the trip end
    trip_begin = start_datetime + timedelta(minutes=settings.buffer_time)
    trip_end = end_datetime - timedelta(minutes=settings.buffer_time)

    # If internal event, set isExternal to False
    if 'Teamworks' in event.summary:
        is_external = False
    else:
        is_external = True

    # Creating the TripData instance
    trip_data = TripData(
        isExternal=is_external,
        isInquiry=False,
        propertyRef=property_doc_ref,
        tripBeginDateTime=trip_begin,
        tripDate=trip_begin.replace(hour=0, minute=0, second=0),  # Set tripDate to be at 00:00:00
        tripEndDateTime=trip_end,
        eventId=event.id,
        eventSummary=event.summary or '',  # Use an empty string if 'summary' is missing
    )

    return trip_data


def process_event(event: Union[GCalEvent, CancelledGCalEvent], property_doc_ref: Any):
    if event.status == 'cancelled':
        handle_cancelled_event(event)
    else:
        handle_validated_event(event, property_doc_ref)


def handle_cancelled_event(event: CancelledGCalEvent):
    existing_trip_ref = db.collection('trips').where('eventId', '==', event.id).get()
    if existing_trip_ref:
        existing_trip_ref[0].reference.delete()
        app_logger.info(f'Deleted trip for cancelled event: {event.id}')


def handle_validated_event(event: GCalEvent, property_doc_ref: Any):
    trip_data = convert_event_to_trip_data(event, property_doc_ref)
    existing_trip_ref = db.collection('trips').where('eventId', '==', event.id).get()
    if existing_trip_ref:
        update_existing_trip(existing_trip_ref[0], trip_data, event)
    else:
        create_new_trip(trip_data, event)


def update_existing_trip(trip_ref, trip_data: TripData, event: GCalEvent):
    trip_ref.reference.update(trip_data.dict())
    app_logger.info(f'Updated trip for event: {event.id}, trip ref: {trip_ref.id}')


def create_new_trip(trip_data: TripData, event: GCalEvent):
    trip_ref = db.collection('trips').add(trip_data.dict())
    app_logger.info(f'Created new trip for event: {event.id}, trip ref: {trip_ref[1].id}')


def clear_event_store(property_ref: str):
    # Get a reference to the 'trips' collection
    trips_ref = db.collection('trips')

    # Get the current time
    now = datetime.utcnow()

    # Query for all documents where 'propertyRef' matches the given property_ref, 'isExternal' is True,
    # and 'tripBeginDateTime' is in the future
    trips = (
        trips_ref.where('propertyRef', '==', property_ref)
        .where('isExternal', '==', True)
        .where('tripBeginDateTime', '>', now)
        .stream()
    )

    # Delete each document
    for trip in trips:
        trip.reference.delete()

    app_logger.info('Event store successfully cleared.')


def delete_calendar_watch_channel(id: str, resource_id: str):
    app_logger.info('Deleting calendar watch channel: %s', id)
    # Call the Google Calendar API to delete the channel
    service = build('calendar', 'v3', credentials=creds)
    try:
        service.channels().stop(body={'id': id, 'resourceId': resource_id}).execute()
        app_logger.info('Calendar watch channel successfully deleted.')
    except HttpError as e:
        app_logger.error('Error deleting calendar watch channel: %s', e)
        raise HTTPException(status_code=400, detail=str(e))


def initalize_trips_from_cal(property_ref: str, calendar_id: str):
    app_logger.info('Initialising trips from calendar: %s , property: %s', calendar_id, property_ref)

    # get the property document
    collection_id, document_id = property_ref.split('/')
    property_doc_ref = db.collection(collection_id).document(document_id)

    # Update the externalCalendar field with the provided calendar_id
    property_doc_ref.update({'externalCalendar': calendar_id})

    # Call the Google Calendar API to fetch the future events
    service = build('calendar', 'v3', credentials=creds)

    # test calendar list
    calendars = service.calendarList().list().execute()
    for calendar_list_entry in calendars['items']:
        app_logger.info(calendar_list_entry['id'], calendar_list_entry['summary'])

    # Set up the webhook
    with logfire.span('setting up webhook for calendar'):
        channel_id = property_ref
        app_logger.info('Setting up webhook and setting the channel_id: %s', property_ref)
        webhook_url = f'{settings.url}/cal_webhook?calendar_id={property_ref}'
        channel = (
            service.events()
            .watch(calendarId=calendar_id, body={'id': channel_id, 'type': 'web_hook', 'address': webhook_url})
            .execute()
        )

        property_doc_ref.update({'channelId': channel['resourceId']})

    sync_calendar_events(property_doc_ref)
    create_events_for_future_trips(property_ref)


def create_events_for_future_trips(property_ref: str):
    with logfire.span(f'create_events_for_future_trips for property: {property_ref}'):
        # Get the current time
        now = datetime.utcnow()

        # Query for all documents where 'propertyRef' matches the given property_ref, 'isExternal' is False,
        # 'eventId' does not exist, and 'tripBeginDateTime' is in the future
        future_trips = (
            db.collection('trips')
            .where('propertyRef', '==', property_ref)
            .where('isExternal', '==', False)
            .where('tripBeginDateTime', '>', now)
            .stream()
        )

        if not future_trips:
            app_logger.info('No future trips found for property: %s', property_ref)
            return

        # For each future trip, create an event and call create_or_update_event_from_trip
        for trip in future_trips:
            trip_data = trip.to_dict()
            app_logger.info('Trip data: %s', trip)
            if 'eventId' not in trip_data:
                # Call create_or_update_event_from_trip to create the event
                app_logger.info('Creating event for trip: %s', trip.reference)
                create_or_update_event_from_trip(property_ref, trip.reference)
            else:
                app_logger.info('Event already exists for trip: %s', trip.reference)


def create_or_update_event_from_trip(property_ref, trip_ref):
    """
    Create or update an event on the Google Calendar associated with the property
    """
    with logfire.span('create_or_update_event_from_trip'):
        # Fetch the specific property document
        property_collection_id, property_document_id = property_ref.split('/')
        property_doc = db.collection(property_collection_id).document(property_document_id).get()

        if property_doc.exists:
            app_logger.info('Property document exists for trip: %s', property_ref)
            property_data = property_doc.to_dict()
            calendar_id = property_data['externalCalendar']

            if calendar_id:
                app_logger.info('Calendar ID: %s', calendar_id)
            else:
                app_logger.error('No external calendar set for property: %s', property_ref)
                raise HTTPException(status_code=400, detail='No external calendar set for property')

            property_name = property_data['propertyName']  # Fetch the property name

            # Fetch the specific trip document
            trip_collection_id, trip_document_id = trip_ref.split('/')
            trip_doc = db.collection(trip_collection_id).document(trip_document_id).get()
            if trip_doc.exists:
                trip_data = trip_doc.to_dict()

                # Fetch the specific user document
                app_logger.info('UserRef: %s', trip_data['userRef'].path)
                collection_id, document_id = trip_data['userRef'].path.split('/')
                user_doc = db.collection(collection_id).document(document_id).get()
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    guest_name = user_data['display_name'] or 'Guest'
                    app_logger.info('Guest name: %s', guest_name)

                    # Construct the booking link
                    booking_link = (
                        f'{settings.app_url}/tripDetails?tripPassed={trip_document_id}&property={property_document_id}'
                    )

                    # Convert the trip data to Google Calendar event format
                    # Add 30-minute buffer time to either side of the event
                    event_data = {
                        'summary': f'Office Booking for {guest_name} | Teamworks',  # Generate the event name
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
                        event_data['id'] = trip_data['eventId']
                        service.events().update(
                            calendarId=calendar_id, eventId=trip_data['eventId'], body=event_data
                        ).execute()
                    else:
                        # get the event id and add it to the trip document
                        event = service.events().insert(calendarId=calendar_id, body=event_data).execute()
                        app_logger.info('Created event: %s', event['id'])
                        trip_doc.reference.update({'eventId': event['id']})

                else:
                    app_logger.error('User document does not exist for: %s', trip_data['userRef'])
                    raise HttpError
            else:
                app_logger.error('Trip document does not exist for: %s', trip_ref)
                raise HttpError
        else:
            app_logger.error('Property document does not exist for: %s', property_ref)
            raise HttpError


def delete_event_from_trip(property_ref, trip_ref):
    """
    Delete an event from the Google Calendar associated with the property
    """
    with logfire.span('delete_event_from_trip'):
        app_logger.info('Deleting event from trip: %s , property: %s', trip_ref, property_ref)
        # Fetch the specific property document
        collection_id, document_id = property_ref.split('/')
        property_doc = db.collection(collection_id).document(document_id).get()

        if property_doc.exists:
            app_logger.info('Property document exists for trip: %s', property_ref)
            property_data = property_doc.to_dict()
            calendar_id = property_data['externalCalendar']

            # Fetch the specific trip document
            collection_id, document_id = trip_ref.split('/')
            trip_doc = db.collection(collection_id).document(document_id).get()
            if trip_doc.exists:
                trip_data = trip_doc.to_dict()

                # Call the Google Calendar API to delete the event
                service = build('calendar', 'v3', credentials=creds)
                service.events().delete(calendarId=calendar_id, eventId=trip_data['eventId']).execute()
            else:
                app_logger.error('Trip document does not exist for: %s', trip_ref)
                raise HttpError
        else:
            app_logger.error('Property document does not exist for: %s', property_ref)
            raise HttpError


def delete_trip_from_event(property_ref, event_id):
    """
    Delete a trip associated with an event from the Firestore database
    """
    with logfire.span('delete_trip_from_event'):
        app_logger.info('Deleting trip associated with event: %s , property: %s', event_id, property_ref)
        # Fetch the specific property document
        collection_id, document_id = property_ref.split('/')
        property_doc = db.collection(collection_id).document(document_id).get()

        if property_doc.exists:
            app_logger.info('Property document exists for event: %s', property_ref)

            # Fetch the specific trip document associated with the event id
            trip_ref = db.collection('trips').where('eventId', '==', event_id).get()
            if trip_ref:
                # Delete the trip document from Firestore
                trip_ref[0].reference.delete()
                app_logger.info('Trip document successfully deleted: %s', trip_ref[0].id)
            else:
                app_logger.error('Trip document does not exist for event: %s', event_id)
                raise HttpError
        else:
            app_logger.error('Property document does not exist for: %s', property_ref)
            raise HttpError
