import requests
from devtools import debug
import firebase_admin
from firebase_admin import firestore, credentials
from google.cloud.firestore_v1 import FieldFilter
from ics import Calendar, Event
from datetime import datetime, timedelta
from urllib.parse import quote

# Initialize Firebase
cred = credentials.Certificate("./teamworks_service_account.json")

app = firebase_admin.initialize_app(cred)
db = firestore.client()


def get_dispute_from_firebase(ref):
    dis = db.child("disputes").child(ref).get()
    return dis.val()


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
        debug(trip.id, trip.to_dict())
            cal_event = Event()
            cal_event.name = f'{trip.name} | {trip.guests} guests | {property_ref.propertyName}'
            cal_event.begin = trip.tripBeginDateTime
            cal_event.end = trip.tripEndDateTime
            cal_event.url = trip.url
            cal.events.add(cal_event)


    debug("reeeeee")
    # doc_ref = db.collection("properties").document(propertyRef)


    # for trip in property_trips:
    #     debug(trip.id, trip.to_dict())
    #
    # # create a calendar from the trips
    #
    # for trip in trips:
    #     # propertyRef = trip.propertyRef #
    #     property = db.child("properties").get()
    #     debug(property)
    #     cal_event = Event()
    #     cal_event.name = trip.name
    #     cal_event.begin = trip.tripBeginDateTime
    #     cal_event.end = trip.tripEndDateTime
    #     cal_event.url = trip.url
    #     cal.events.add(cal_event)

    cal_link = "test"

    return cal_link


def nica_demo(ref):
    trip = db.child("trips").child(ref)
    trip.update({"guests": "7"})
