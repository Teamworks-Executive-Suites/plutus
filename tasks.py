import requests
from devtools import debug
import firebase_admin
from firebase_admin import firestore, credentials
from google.cloud.firestore_v1 import FieldFilter
from ics import Calendar, Event
import os
from datetime import datetime, timedelta
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


# On realtime updates:
callback_done = threading.Event()
def on_snapshot(doc_snapshot, changes, read_time):
    for doc in doc_snapshot:
        create_cal_for_property(doc.property_ref)
    callback_done.set()

 # on change to trips
 # for property in properties:
 #     create_cal_for_property(property)
