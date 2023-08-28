import requests
from devtools import debug
import firebase_admin
from firebase_admin import firestore, credentials
from google.cloud.firestore_v1 import FieldFilter
from icalendar import Calendar as iCalCalendar
from ics import Calendar, Event
import os
from datetime import datetime, timezone
from urllib.parse import quote
import threading

# Initialize Firebase
cred = credentials.Certificate("./teamworks_service_account.json")

app = firebase_admin.initialize_app(cred)
db = firestore.client()


def get_dispute_from_firebase(ref):
    dis = db.child("disputes").child(ref).get()
    return dis.val()



# Calendar stuff


def create_cal_for_property(propertyRef):
    debug(propertyRef)

    trips_ref = db.collection("trips")

    # Here we get all trips with a tripTax of 6
    # property_trips = trips_ref.where("tripTax", "==", 6).stream()

    collection_id, document_id = propertyRef.split('/')

    property_ref = db.collection(collection_id).document(document_id).get()
    debug(property_ref.to_dict())
    property_trips = trips_ref.where("propertyRef", "==", property_ref.reference).stream()

    cal = Calendar()
    for trip in property_trips:

        user_ref = trip.get("userRef").id
        debug(user_ref)
        user = db.collection("users").document(user_ref).get()
        debug(trip.to_dict())
        debug(f'{user.get("email")} | {property_ref.get("propertyName")}')

        cal_event = Event()
        cal_event.name = f'{user.get("email")} | {property_ref.get("propertyName")}'
        cal_event.begin = trip.get("tripBeginDateTime")
        cal_event.end = trip.get("tripEndDateTime")

        cal.events.add(cal_event)

    # Create an .ics file
    ics_file_path = f'calendars/{property_ref.get("propertyName")}.ics'
    with open(ics_file_path, "w") as ics_file:
        ics_file.writelines(cal)

    return ics_file_path



def create_trips_from_ics(property_ref, ics_link, external_source):
    collection_id, document_id = property_ref.split('/')

    property_ref = db.collection(collection_id).document(document_id).get()

    response = requests.get(ics_link)
    if response.status_code != 200:
        return "Failed to fetch the iCalendar file."

    # cal = Calendar.from_ical(response.content)
    # trips_ref = db.collection("trips")

    ics_data = response.text

    cal = iCalCalendar.from_ical(ics_data)
    trips_ref = db.collection("trips")

    for event in cal.walk('VEVENT'):
        debug(event)

        # convert ical datetime to firestore datetime
        eventstart = event.get('DTSTART').dt
        eventend = event.get('DTEND').dt

        tz = timezone.utc
        trip_begin_datetime = datetime(eventstart.year, eventstart.month, eventstart.day, tzinfo=tz)
        trip_end_datetime = datetime(eventend.year, eventend.month, eventend.day, tzinfo=tz)
        debug(trip_begin_datetime)
        debug(trip_end_datetime)

    trip_data = {
            "externalSource": external_source,
            "propertyRef": property_ref.reference,
            "tripBeginDateTime": trip_begin_datetime,
            "tripEndDateTime": trip_end_datetime,
        }
    debug(trip_data)
    trips_ref.add(trip_data)

    return True


# On realtime updates:
# callback_done = threading.Event()
# def on_snapshot(doc_snapshot, changes, read_time):
#     debug(f"Received document snapshot")
#     for doc in doc_snapshot:
#         debug(doc.to_dict())
#     callback_done.set()

# def start_watch():
#     doc_ref = db.collection("properties")
#     query_watch = db.collection('trips').on_snapshot(on_snapshot)
#
#     doc_watch = doc_ref.on_snapshot(on_snapshot)
#
# # https://firebase.google.com/docs/firestore/query-data/listen
# # for property in properties:
# #     create_cal_for_property(property)
#
# start_watch()

# add to database using calendar information