import logging
import os
from datetime import datetime

import requests
from google.cloud.firestore_v1 import FieldFilter
from icalendar import Calendar as iCalCalendar
from ics import Calendar, Event

from app.firebase_setup import current_time, db, tz


def create_cal_for_property(propertyRef):
    logging.info('create_cal_for_property')

    collection_id, document_id = propertyRef.split('/')
    trips_ref = db.collection('trips')
    property_ref = db.collection('properties').document(document_id).get()
    property_trips = (
        trips_ref.where(filter=FieldFilter('propertyRef', '==', property_ref.reference))
        .where(filter=FieldFilter('isExternal', '==', False))
        .stream()
    )

    ics_file_path = f'app/static/calendars/{property_ref.get("propertyName")}.ics'

    # If calendar file exists, load it, else create a new calendar
    if os.path.exists(ics_file_path):
        with open(ics_file_path, 'r') as ics_file:
            cal = Calendar(ics_file.read())
    else:
        cal = Calendar()

    for trip in property_trips:
        trip_begin_datetime = trip.get('tripBeginDateTime')

        # Check if the trip is in the future
        if trip_begin_datetime > current_time:
            user_ref = trip.get('userRef').id
            user = db.collection('users').document(user_ref).get()
            logging.info(f'{user.get("email")} | {property_ref.get("propertyName")}')

            cal_event = Event()
            cal_event.name = f'{user.get("email")} | {property_ref.get("propertyName")}'
            cal_event.begin = trip_begin_datetime
            cal_event.end = trip.get('tripEndDateTime')

            # Adding event to the calendar
            cal.events.add(cal_event)

    # Writing the updated calendar back to the file
    with open(ics_file_path, 'w') as ics_file:
        ics_file.writelines(cal)

    return ics_file_path


def create_trips_from_ics(property_ref, ics_link):
    logging.info('create_trips_from_ics')

    collection_id, document_id = property_ref.split('/')

    property_ref = db.collection(collection_id).document(document_id).get()

    response = requests.get(ics_link)
    if response.status_code != 200:
        return 'Failed to fetch the iCalendar file.'

    ics_data = response.text

    cal = iCalCalendar.from_ical(ics_data)
    trips_ref = db.collection('trips')

    for event in cal.walk('VEVENT'):
        logging.info(event)

        # convert ical datetime to firestore datetime
        eventstart = event.get('DTSTART').dt

        # Check if the event is in the future
        if eventstart > current_time:
            eventend = event.get('DTEND').dt

            trip_begin_datetime = datetime(eventstart.year, eventstart.month, eventstart.day, tzinfo=tz)
            trip_end_datetime = datetime(eventend.year, eventend.month, eventend.day, tzinfo=tz)

            trip_data = {
                'isExternal': True,
                'propertyRef': property_ref.reference,
                'tripBeginDateTime': trip_begin_datetime,
                'tripEndDateTime': trip_end_datetime,
            }
            trips_ref.add(trip_data)

    return True


def update_calendars():
    logging.info('Updating Calendars')

    properties_ref = db.collection('properties')
    properties = properties_ref.stream()

    for prop in properties:
        # Sync External Calendars
        try:
            external_calendar_data = prop.get('externalCalendar')
            if external_calendar_data and external_calendar_data.exists:
                create_trips_from_ics(prop.reference, external_calendar_data)
        except KeyError:
            pass  # Handle the case where the "externalCalendar" key doesn't exist

        # Sync Internal Calendars
        create_cal_for_property(prop.reference.path)

    return True
