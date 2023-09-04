import json
import os
from datetime import datetime, timezone

import firebase_admin
import requests
import stripe
from devtools import debug
from dotenv import load_dotenv
from firebase_admin import firestore, credentials
from google.cloud.firestore_v1 import FieldFilter
from icalendar import Calendar as iCalCalendar
from ics import Calendar, Event

load_dotenv()
tz = timezone.utc

# Initialize Firebase
cred = credentials.Certificate(json.loads(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')))

app = firebase_admin.initialize_app(cred)
db = firestore.client()

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


# Stripe stuff
def get_trip_document(trip_ref):
    collection_id, document_id = trip_ref.split('/')
    trip = db.collection(collection_id).document(document_id).get()
    return trip


def get_dispute_by_trip_ref(trip_ref):
    dispute_query = db.collection('disputes').where(filter=FieldFilter("tripRef", "==", trip_ref)).limit(1)
    dispute_documents = list(dispute_query.stream())
    return dispute_documents[0] if dispute_documents else None


def process_refund(charge_id, amount):
    try:
        refund = stripe.Refund.create(
            charge=charge_id,
            amount=amount,
        )
        return refund.status == 'succeeded'
    except Exception as e:
        return f"An error occurred: {str(e)}"


def refund_logic(payment_intent_id, trip_deposit, dispute_amount):
    try:
        charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)
        if charge.data:
            refund_amount = int((trip_deposit - dispute_amount) * 100)
            return process_refund(charge.data[0].id, refund_amount)
        else:
            return "Charge not found."
    except Exception as e:
        return f"An error occurred: {str(e)}"


def handle_dispute_and_refund(trip_ref):
    trip = get_trip_document(trip_ref)

    if not trip.exists:
        return "Trip document not found."

    dispute = get_dispute_by_trip_ref(trip.reference)

    if not dispute:
        payment_intent_id = trip.get("paymentMethod")
        return refund_logic(payment_intent_id, trip.get("tripDeposit"), 0)  # Full refund

    payment_intent_id = dispute.get("tripPaymentId")
    return refund_logic(payment_intent_id, trip.get("tripDeposit"), dispute.get("disputeAmount"))


# Calendar stuff

def create_cal_for_property(propertyRef):
    debug("create_cal_for_property")

    debug(propertyRef)

    collection_id, document_id = propertyRef.split('/')
    trips_ref = db.collection("trips")
    property_ref = db.collection('properties').document(document_id).get()
    property_trips = (trips_ref
                      .where(filter=FieldFilter("propertyRef", "==", property_ref.reference))
                      .where(filter=FieldFilter("isExternal", "==", False))
                      .stream()
                      )

    # check if trip has been completed
    current_time = datetime.now(tz)

    cal = Calendar()
    for trip in property_trips:
        user_ref = trip.get("userRef").id
        user = db.collection("users").document(user_ref).get()
        debug(f'{user.get("email")} | {property_ref.get("propertyName")}')

        cal_event = Event()
        cal_event.name = f'{user.get("email")} | {property_ref.get("propertyName")}'
        cal_event.begin = trip.get("tripBeginDateTime")
        cal_event.end = trip.get("tripEndDateTime")

        if current_time > trip.get("tripEndDateTime"):
            trip.reference.update({"isComplete": True})

        cal.events.add(cal_event)


    # Create an .ics file
    ics_file_path = f'calendars/{property_ref.get("propertyName")}.ics'
    with open(ics_file_path, "w") as ics_file:
        ics_file.writelines(cal)

    return ics_file_path


def create_trips_from_ics(property_ref, ics_link):
    debug("create_trips_from_ics")

    collection_id, document_id = property_ref.split('/')

    property_ref = db.collection(collection_id).document(document_id).get()

    response = requests.get(ics_link)
    if response.status_code != 200:
        return "Failed to fetch the iCalendar file."

    ics_data = response.text

    cal = iCalCalendar.from_ical(ics_data)
    trips_ref = db.collection("trips")

    for event in cal.walk('VEVENT'):
        debug(event)

        # convert ical datetime to firestore datetime
        eventstart = event.get('DTSTART').dt
        eventend = event.get('DTEND').dt

        trip_begin_datetime = datetime(eventstart.year, eventstart.month, eventstart.day, tzinfo=tz)
        trip_end_datetime = datetime(eventend.year, eventend.month, eventend.day, tzinfo=tz)

        trip_data = {
            "isExternal": True,
            "propertyRef": property_ref.reference,
            "tripBeginDateTime": trip_begin_datetime,
            "tripEndDateTime": trip_end_datetime,
        }
        trips_ref.add(trip_data)

    return True


debug("Starting Calendar Sync")


def update_calendars():
    debug("Updating Calendars")

    properties_ref = db.collection("properties")
    properties = properties_ref.stream()

    for prop in properties:

        # Sync External Calendars
        try:
            external_calendar_data = prop.get("externalCalendar")
            if external_calendar_data and external_calendar_data.exists:
                create_trips_from_ics(prop.reference, external_calendar_data)
        except KeyError:
            pass  # Handle the case where the "externalCalendar" key doesn't exist

        # Sync Internal Calendars
        create_cal_for_property(prop.reference.path)

    return True
