import json
import requests
from devtools import debug
import firebase_admin
from firebase_admin import firestore, credentials
from icalendar import Calendar as iCalCalendar
from ics import Calendar, Event
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
import stripe

load_dotenv()

# Initialize Firebase
cred = credentials.Certificate(json.loads(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')))

app = firebase_admin.initialize_app(cred)
db = firestore.client()


stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

def get_dispute_from_firebase(trip_ref):
    collection_id, document_id = trip_ref.split('/')
    trip = db.collection(collection_id).document(document_id).get()
    debug(trip.reference)
    debug('reeeeeeeeeeeeeeeeee')
    dispute = db.collection('disputes').where("tripRef", "==", trip.reference).stream()


    if not trip.exists:
        return "Trip document not found."

    dispute_query = db.collection('disputes').where("tripRef", "==", trip.reference).limit(1)
    dispute_documents = dispute_query.stream()

    # Check if there are any dispute documents
    if not trip.exists:
        return "Trip document not found."

    dispute_query = db.collection('disputes').where("tripRef", "==", trip.reference).limit(1)
    dispute_documents = list(dispute_query.stream())

    # Check if there are any dispute documents
    if len(dispute_documents) == 0:
        return "Dispute document not found."

    dispute = dispute_documents[0]  # Get the first dispute document

    payment_intent_id = dispute.get("tripPaymentId")

    if not payment_intent_id:
        return "Payment ID not found in the dispute document."

    try:
        charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)
        if charge.data:
            refund = stripe.Refund.create(
                charge=charge.data[0].id,
                amount=int(dispute.get("disputeAmount") * 100),
            )
            if refund.status == 'succeeded':
                return "Refund successful."
            else:
                return "Refund failed."
        else:
            return "Charge not found."
    except Exception as e:
        return f"An error occurred: {str(e)}"


# Calendar stuff

debug("create_cal_for_property")
def create_cal_for_property(propertyRef):
    debug(propertyRef)

    collection_id, document_id = propertyRef.split('/')


    trips_ref = db.collection("trips")

    # Here we get all trips with a tripTax of 6
    # property_trips = trips_ref.where("tripTax", "==", 6).stream()

    property_ref = db.collection('properties').document(document_id).get()
    property_trips = (trips_ref
                      .where("propertyRef", "==", property_ref.reference)
                      .where("isExternal", "==", False)
                      .stream()
                      )

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


debug("create_trips from ics")
def create_trips_from_ics(property_ref, ics_link):
    tz = timezone.utc

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

        trip_begin_datetime = datetime(eventstart.year, eventstart.month, eventstart.day, tzinfo=tz)
        trip_end_datetime = datetime(eventend.year, eventend.month, eventend.day, tzinfo=tz)
        debug(trip_begin_datetime)
        debug(trip_end_datetime)

        trip_data = {
                "isExternal": True,
                "propertyRef": property_ref.reference,
                "tripBeginDateTime": trip_begin_datetime,
                "tripEndDateTime": trip_end_datetime,
            }
        debug(trip_data)
        trips_ref.add(trip_data)

    return True

debug("Starting Calendar Sync")
def update_calendars():
    debug("Updating Calendars")

    properties_ref = db.collection("properties")
    properties = properties_ref.stream()

    for property in properties:

        # Sync External Calendars
        try:
            external_calendar_data = property.get("externalCalendar")
            if external_calendar_data and external_calendar_data.exists:
                create_trips_from_ics(property.reference, external_calendar_data)
        except KeyError:
            pass  # Handle the case where the "externalCalendar" key doesn't exist

        debug(property.reference.path)
        # Sync Internal Calendars
        create_cal_for_property(property.reference.path)

    return True


# On realtime updates:
# callback_done = threading.Event()
# def on_snapshot(doc_snapshot, changes, read_time):
#     debug(f"Received document snapshot")
#     for doc in doc_snapshot:
#         debug(doc.to_dict())
#     callback_done.set()

#update every hour

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