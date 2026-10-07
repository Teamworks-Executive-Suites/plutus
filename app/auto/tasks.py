import base64
from datetime import datetime, timedelta, timezone

import logfire
import requests
from google.cloud.firestore_v1 import ArrayUnion, FieldFilter
from pytz import timezone as timezone_of

from app.auto._utils import app_logger, document_id
from app.firebase_setup import db
from app.utils import settings


def get_contact_details(trip_doc, property_doc):
    """Get host and guest contact details from already-fetched trip/property docs.

    Both refs go through `document_id`, which is the only thing that copes with
    all three shapes these fields hold. This function used to read the two refs
    with two DIFFERENT assumptions on adjacent lines — `.id` on the property's,
    which raises AttributeError on a path string, and a raw pass to
    `.document()` on the trip's, which raises ValueError on anything that is not
    a string. The Flutter app writes `trips.userRef` as a DocumentReference, so
    the second one raised on essentially every trip.

    That raise was not contained to the SMS: in the completion cron the SMS and
    the completion email share a try block, so it took the email with it and
    logged 'Failed to complete trip' for a trip that had completed fine.
    """
    with logfire.span('get_contact_details'):
        # Read through to_dict(): DocumentSnapshot.get() raises KeyError on an
        # ABSENT field, and `userRef` genuinely is absent — 34 of 40 live trips
        # have none, because the booking funnel writes a draft before anyone
        # signs in. Same reason `resolve_host_user_ref` does it this way.
        trip_data = trip_doc.to_dict() or {}
        property_data = property_doc.to_dict() or {}

        host_id = document_id(property_data.get('userRef'))
        host_doc = db.collection('users').document(host_id).get() if host_id else None
        if host_doc is None or not host_doc.exists:
            app_logger.error('Host document does not exist for property: %s', property_doc.id)
            return None, None

        if host_doc.get('smsOptIn'):
            host_numbers = host_doc.get('phone_numbers')
        else:
            host_numbers = None

        guest_id = document_id(trip_data.get('userRef'))
        guest_doc = db.collection('users').document(guest_id).get() if guest_id else None
        if guest_doc is None or not guest_doc.exists:
            app_logger.error('Guest document does not exist for trip: %s', trip_doc.id)
            return None, None

        if guest_doc.get('smsOptIn'):
            guest_number = guest_doc.get('phone_numbers')[0]
        else:
            guest_number = None

        return host_numbers, guest_number


def send_sms(to: str, body: str):
    """
    Function to send an SMS to a phone number using Twilio API.
    """
    with logfire.span('send_sms'):
        # Twilio API URL
        url = f'https://api.twilio.com/2010-04-01/Accounts/{settings.t_account_sid}/Messages'

        # Twilio Account SID and Auth Token
        account_sid = settings.t_account_sid
        auth_token = settings.t_auth_token

        # Base64 encode the Account SID and Auth Token
        credentials = base64.b64encode(f'{account_sid}:{auth_token}'.encode('utf-8')).decode('utf-8')

        # Headers for the request
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': f'Basic {credentials}'}

        # Data for the request
        data = {
            'To': to,
            'Body': body,
            'From': settings.t_from_number,
            'MessagingServicesSid': settings.t_messaging_service_sid,
        }

        # Send the request
        response = requests.post(url, headers=headers, data=data)

        # Log the response
        app_logger.info('SMS sent to %s: %s', to, body)
        app_logger.info('Response: %s', response.text)


def complete_trip_sms(trip_doc, property_doc):
    with logfire.span('complete_trip_sms'):
        host_numbers, guest_number = get_contact_details(trip_doc, property_doc)
        property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_doc.id}&property={property_doc.id}'

        if host_numbers:
            for host_num in host_numbers:
                send_sms(host_num, f'Your trip {trip_doc.id} has been completed. View here: {property_link}')

        if guest_number:
            send_sms(
                guest_number,
                f'Your trip {trip_doc.id} has been completed. Please review the host. View here: {property_link}',
            )


def send_reminder_sms(trip_doc, property_doc, time: int):
    host_numbers, guest_number = get_contact_details(trip_doc, property_doc)
    property_link = f'{settings.app_url}/tripDetails?tripPassed={trip_doc.id}&property={property_doc.id}'

    # Send SMS to host and guest
    if guest_number:
        send_sms(
            guest_number, f'Reminder: Your booking {trip_doc.id} starts in {time} hours. View here: {property_link}'
        )

    if host_numbers:
        for host_num in host_numbers:
            send_sms(
                host_num, f'Reminder: Your booking {trip_doc.id} starts in {time} hours. View here: {property_link}'
            )


def local_time_for_email(value, property_timezone):
    """A booking time as the guest and host would say it, not as UTC.

    Trip times are stored UTC; the property's IANA zone lives on the property.
    This f-stringed the raw value, so a 9:00 AM Los Angeles booking arrived in
    both inboxes as `2026-07-15 16:00:00+00:00` — seven hours out, in a format
    nobody reads, on the one email that tells someone when to turn up.

    Falls back to the raw value rather than raising: an email with an ugly time
    beats no email at all, and this runs after the booking is already made.
    """
    if value is None:
        return ''
    if not property_timezone:
        return f'{value}'
    try:
        return value.astimezone(timezone_of(property_timezone)).strftime('%a %d %b %Y, %I:%M %p')
    except Exception as err:  # noqa: BLE001 - never fail an email over formatting
        app_logger.warning('Could not render %s in %s: %s', value, property_timezone, err)
        return f'{value}'


def send_booking_email(trip_doc, event: str, time: int | None = None):
    """Ask the website to send the emails for a booking event.

    Plutus holds no mail credential and no template ids. It names an event and
    a trip; the route reads the trip back, resolves both addresses itself and
    decides which templates go to whom. One implementation of "what does a
    booking confirmation say", shared with the site and the app.

    This replaced `sendgrid_email`, which built a SendGrid payload by hand —
    addresses, template id, every variable — and had never delivered a message:
    the SendGrid account has had zero sending credits since May, so every one of
    these posts was answered and discarded.

    Failure is logged and swallowed. This is called from the completion and
    reminder crons, and marking a trip complete matters more than telling
    someone about it; an exception here would abandon the rest of the sweep.
    """
    if not settings.email_service_secret:
        app_logger.error('EMAIL_SERVICE_SECRET is not set; cannot send %s for %s', event, trip_doc.id)
        return

    payload = {'event': event, 'tripId': trip_doc.id}
    if time is not None:
        payload['params'] = {'time': str(time)}

    try:
        r = requests.post(
            f'{settings.site_url}/api/email',
            json=payload,
            headers={'x-email-service-secret': settings.email_service_secret},
            timeout=20,
        )
        if r.status_code != 200:
            app_logger.error('Email route answered %s for %s %s: %s', r.status_code, event, trip_doc.id, r.text[:200])
            return
        app_logger.info('Sent %s for trip %s: %s', event, trip_doc.id, r.text[:200])
    except requests.RequestException as e:
        app_logger.error('Could not reach the email route for %s %s: %s', event, trip_doc.id, e)


def send_complete_email(trip_doc, property_doc):
    with logfire.span('send_complete_email'):
        send_booking_email(trip_doc, 'booking-complete')


def send_reminder_email(trip_doc, property_doc, time: int):
    with logfire.span('send_reminder_email'):
        send_booking_email(trip_doc, 'booking-reminder', time)


def auto_complete_and_notify():
    """
    Automatically mark completed trips and send reminders.
    Uses two targeted Firestore queries instead of iterating all properties/trips.
    """
    with logfire.span('auto_complete_and_notify'):
        now = datetime.now(timezone.utc)
        reminder_cutoff = now + timedelta(hours=25)

        # --- Completion: trips past their end time that aren't marked complete ---
        with logfire.span('completion_query'):
            completion_trips = (
                db.collection('trips')
                .where(filter=FieldFilter('upcoming', '==', True))
                .where(filter=FieldFilter('tripEndDateTime', '<=', now))
                .stream()
            )

            for trip in completion_trips:
                trip_dict = trip.to_dict()

                # A cancelled booking is not a booking.
                #
                # Cancelling writes `cancelTrip: true` and leaves `upcoming`
                # alone — `upcoming` means "live", not "paid", and nothing
                # clears it. This query filters on `upcoming` and never looked
                # at `cancelTrip`, so a guest who cancelled still got "your trip
                # is tomorrow", and after the end time the completion branch
                # marked the trip `complete` and asked both parties to review
                # a stay that never happened.
                #
                # Read through the dict, where an absent field is None and so
                # falsy — a trip written before the flag existed is not
                # cancelled, and `DocumentSnapshot.get()` would raise on it.
                if trip_dict.get('cancelTrip', False):
                    continue

                if trip_dict.get('isExternal', False) or trip_dict.get('isBlocked', False):
                    continue

                if trip_dict.get('complete', False):
                    continue

                property_ref = trip_dict.get('propertyRef')
                if not property_ref:
                    app_logger.error('Trip %s has no propertyRef', trip.id)
                    continue

                property_doc = property_ref.get()
                if not property_doc.exists:
                    app_logger.error('Property document not found for trip %s', trip.id)
                    continue

                with logfire.span(f'Completing trip: {trip.id}'):
                    # One try per thing that can fail independently, matching the
                    # reminder branch below. They used to share a block, so a
                    # raise in the SMS took the completion EMAIL with it and then
                    # logged 'Failed to complete trip' for a trip that had in
                    # fact completed — the state change is the first statement
                    # and had already committed.
                    try:
                        trip.reference.update({'complete': True, 'completeDate': now, 'upcoming': False})
                        app_logger.info('Trip %s marked as complete', trip.id)
                    except Exception as e:
                        app_logger.error('Failed to complete trip %s: %s', trip.id, e)
                        continue

                    try:
                        complete_trip_sms(trip, property_doc)
                    except Exception as e:
                        app_logger.error('Trip %s completed but its SMS failed: %s', trip.id, e)

                    try:
                        send_complete_email(trip, property_doc)
                    except Exception as e:
                        app_logger.error('Trip %s completed but its email failed: %s', trip.id, e)

        # --- Reminders: upcoming trips starting within the next 25 hours ---
        with logfire.span('reminder_query'):
            reminder_trips = (
                db.collection('trips')
                .where(filter=FieldFilter('upcoming', '==', True))
                .where(filter=FieldFilter('tripBeginDateTime', '>', now))
                .where(filter=FieldFilter('tripBeginDateTime', '<=', reminder_cutoff))
                .stream()
            )

            for trip in reminder_trips:
                trip_dict = trip.to_dict()

                # A cancelled booking is not a booking.
                #
                # Cancelling writes `cancelTrip: true` and leaves `upcoming`
                # alone — `upcoming` means "live", not "paid", and nothing
                # clears it. This query filters on `upcoming` and never looked
                # at `cancelTrip`, so a guest who cancelled still got "your trip
                # is tomorrow", and after the end time the completion branch
                # marked the trip `complete` and asked both parties to review
                # a stay that never happened.
                #
                # Read through the dict, where an absent field is None and so
                # falsy — a trip written before the flag existed is not
                # cancelled, and `DocumentSnapshot.get()` would raise on it.
                if trip_dict.get('cancelTrip', False):
                    continue

                if trip_dict.get('isExternal', False) or trip_dict.get('isBlocked', False):
                    continue

                property_ref = trip_dict.get('propertyRef')
                if not property_ref:
                    app_logger.error('Trip %s has no propertyRef', trip.id)
                    continue

                property_doc = property_ref.get()
                if not property_doc.exists:
                    app_logger.error('Property document not found for trip %s', trip.id)
                    continue

                time_difference = trip_dict['tripBeginDateTime'] - now

                # Which reminders this trip has already had.
                #
                # The 24-hour window is TWO HOURS WIDE (23h to 25h) on an
                # HOURLY cron, so a trip sits inside it on two consecutive runs
                # and both parties were texted and emailed twice. The 1-hour
                # window is an hour wide, which is exactly the cadence — so it
                # fires once when the schedule is punctual and twice when it
                # drifts, which is worse than either.
                #
                # Widening or narrowing the windows only moves the problem: a
                # window that cannot double-fire also cannot survive a missed
                # run. What fixes it is remembering, so the record of having
                # sent is what the next run reads.
                sent = trip_dict.get('remindersSent') or []

                with logfire.span(f'Reminder check for trip {trip.id}: starts in {time_difference}'):
                    # 24-hour reminder
                    if timedelta(hours=23) < time_difference < timedelta(hours=25) and '24h' not in sent:
                        # Marked BEFORE sending, not after. A send that raises
                        # is caught and logged below, and a reminder that went
                        # out and then failed to record would go out again on
                        # the next run — the very thing this is here to stop.
                        # Losing one reminder to a crash is better than sending
                        # it twice every hour.
                        trip.reference.update({'remindersSent': ArrayUnion(['24h'])})
                        try:
                            send_reminder_sms(trip, property_doc, 24)
                        except Exception as e:
                            app_logger.error('Failed to send 24h reminder SMS for trip %s: %s', trip.id, e)

                        try:
                            send_reminder_email(trip, property_doc, 24)
                        except Exception as e:
                            app_logger.error('Failed to send 24h reminder email for trip %s: %s', trip.id, e)

                    # 1-hour reminder (30min window each side to match hourly schedule)
                    if timedelta(minutes=30) < time_difference < timedelta(hours=1, minutes=30) and '1h' not in sent:
                        trip.reference.update({'remindersSent': ArrayUnion(['1h'])})
                        try:
                            send_reminder_sms(trip, property_doc, 1)
                        except Exception as e:
                            app_logger.error('Failed to send 1h reminder SMS for trip %s: %s', trip.id, e)

                        try:
                            send_reminder_email(trip, property_doc, 1)
                        except Exception as e:
                            app_logger.error('Failed to send 1h reminder email for trip %s: %s', trip.id, e)

    return True
