import os

# Must be set before app.settings / app.firebase_setup load so `db` binds to the
# in-memory MockFirestore rather than a real Firestore client.
os.environ['TESTING'] = 'true'

from datetime import datetime, timezone  # noqa: E402
from unittest import TestCase  # noqa: E402
from unittest.mock import patch  # noqa: E402

import httplib2  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.cal.tasks import (  # noqa: E402
    calendar_event_id_for_trip,
    create_or_update_event_from_trip,
    is_eligible_for_event_backfill,
    update_existing_trip,
)
from app.firebase_setup import MOCK_DB  # noqa: E402
from app.models import TripData  # noqa: E402

BEGIN = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)


class _StubEvent:
    """Stand-in for GCalEvent; update_existing_trip only reads `.id`."""

    id = 'evt_stub'


def _confirmed_booking(**overrides):
    trip = {
        'isExternal': False,
        'isInquiry': False,
        'isOffer': False,
        'cancelTrip': False,
        'isBlocked': False,
    }
    trip.update(overrides)
    return trip


class TestIsCalendarEligible(TestCase):
    """A calendar event must only ever be created for a real, held booking.

    Regression guard for trip lpIbpX4hMByLuj4cJNVr: an unpaid inquiry was given a
    Google Calendar event, and the resulting sync then flipped isInquiry to False,
    silently promoting it to a confirmed booking.
    """

    def test_confirmed_booking_is_eligible(self):
        self.assertTrue(is_eligible_for_event_backfill(_confirmed_booking()))

    def test_inquiry_is_not_eligible(self):
        self.assertFalse(is_eligible_for_event_backfill(_confirmed_booking(isInquiry=True)))

    def test_offer_awaiting_payment_is_not_eligible(self):
        self.assertFalse(is_eligible_for_event_backfill(_confirmed_booking(isOffer=True)))

    def test_cancelled_trip_is_not_eligible(self):
        self.assertFalse(is_eligible_for_event_backfill(_confirmed_booking(cancelTrip=True)))

    def test_host_blocked_time_is_eligible(self):
        # Blocked time holds the calendar even though it is not a paid booking.
        blocked = _confirmed_booking(isBlocked=True, isInquiry=True, isOffer=True)
        self.assertTrue(is_eligible_for_event_backfill(blocked))

    def test_missing_flags_default_to_not_eligible(self):
        # A half-written trip doc must not be given a calendar event.
        self.assertFalse(is_eligible_for_event_backfill({}))


class TestCalendarEventIdForTrip(TestCase):
    """Deterministic event IDs make insert idempotent, killing the duplicate-event race."""

    def test_is_deterministic(self):
        self.assertEqual(
            calendar_event_id_for_trip('lpIbpX4hMByLuj4cJNVr'),
            calendar_event_id_for_trip('lpIbpX4hMByLuj4cJNVr'),
        )

    def test_differs_between_trips(self):
        self.assertNotEqual(
            calendar_event_id_for_trip('lpIbpX4hMByLuj4cJNVr'),
            calendar_event_id_for_trip('19q4kp60qvbjnged6g0k1beh2o'),
        )

    def test_uses_charset_google_calendar_accepts(self):
        # Google requires base32hex: characters a-v and 0-9, length 5-1024.
        event_id = calendar_event_id_for_trip('lpIbpX4hMByLuj4cJNVr')
        self.assertRegex(event_id, r'^[a-v0-9]{5,1024}$')


class TestUpdateExistingTrip(TestCase):
    """Calendar sync owns times; it must never rewrite booking-state fields."""

    def setUp(self):
        self.db = MOCK_DB
        self.trip_id = 'existing_trip'
        self.db.collection('trips').document(self.trip_id).set(
            {
                'isInquiry': True,
                'isOffer': True,
                'upcoming': True,
                'tripCreated': datetime(2026, 5, 20, 16, 31, tzinfo=timezone.utc),
                'tripBeginDateTime': BEGIN,
                'tripEndDateTime': END,
                'eventId': 'evt_stub',
                'eventSummary': 'Old summary',
            }
        )
        self.trip_data = TripData(
            tripCreated=datetime(2026, 5, 21, 3, 40, tzinfo=timezone.utc),
            isExternal=False,
            isInquiry=False,
            propertyRef=None,
            tripBeginDateTime=datetime(2026, 8, 18, 16, 0, tzinfo=timezone.utc),
            tripDate=datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc),
            tripEndDateTime=datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc),
            eventId='evt_stub',
            eventSummary='New summary',
        )

    def _run_and_reload(self):
        snapshot = self.db.collection('trips').document(self.trip_id).get()
        update_existing_trip(snapshot, self.trip_data, _StubEvent())
        return self.db.collection('trips').document(self.trip_id).get().to_dict()

    def test_does_not_overwrite_is_inquiry(self):
        self.assertTrue(self._run_and_reload()['isInquiry'])

    def test_does_not_overwrite_is_offer(self):
        self.assertTrue(self._run_and_reload()['isOffer'])

    def test_does_not_overwrite_trip_created(self):
        self.assertEqual(
            self._run_and_reload()['tripCreated'],
            datetime(2026, 5, 20, 16, 31, tzinfo=timezone.utc),
        )

    def test_updates_times_from_the_calendar(self):
        result = self._run_and_reload()
        self.assertEqual(result['tripBeginDateTime'], datetime(2026, 8, 18, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(result['tripEndDateTime'], datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc))

    def test_updates_event_summary(self):
        self.assertEqual(self._run_and_reload()['eventSummary'], 'New summary')


class _PathRef:
    """MockFirestore refs have no `.path`; production code reads userRef.path."""

    def __init__(self, path):
        self.path = path


class _Request:
    def __init__(self, result, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class _FakeEvents:
    def __init__(self, insert_error=None):
        self.inserted = []
        self.updated = []
        self._insert_error = insert_error

    def insert(self, calendarId, body):
        self.inserted.append(body)
        # Google assigns a random ID when the caller does not supply one.
        return _Request({'id': body.get('id', 'google_random_id')}, self._insert_error)

    def update(self, calendarId, eventId, body):
        self.updated.append(eventId)
        return _Request({'id': eventId})


class _FakeCalendarService:
    def __init__(self, events):
        self._events = events

    def events(self):
        return self._events


def _conflict_error():
    return HttpError(httplib2.Response({'status': 409}), b'The requested identifier already exists.')


class TestCreateEventFromTrip(TestCase):
    """Event IDs must be derived from the trip so concurrent syncs cannot duplicate.

    Regression guard for trip lpIbpX4hMByLuj4cJNVr, which got two calendar events
    369ms apart; the second had no matching trip and became a phantom trip doc.
    """

    TRIP_ID = 'lpIbpX4hMByLuj4cJNVr'
    PROPERTY_ID = 'Us1f1bl7NC0TfAfQeITb'

    def setUp(self):
        self.db = MOCK_DB
        self.db.collection('properties').document(self.PROPERTY_ID).set(
            {'externalCalendar': 'cal@group.calendar.google.com', 'propertyName': 'Suite 14'}
        )
        self.db.collection('users').document('guest_uid').set({'display_name': 'Ada'})
        self.db.collection('trips').document(self.TRIP_ID).set(
            {
                'userRef': _PathRef('users/guest_uid'),
                'tripBeginDateTime': BEGIN,
                'tripEndDateTime': END,
                'isBlocked': False,
            }
        )

    def _run(self, insert_error=None):
        events = _FakeEvents(insert_error=insert_error)
        with patch('app.cal.tasks.build', return_value=_FakeCalendarService(events)):
            create_or_update_event_from_trip(f'properties/{self.PROPERTY_ID}', f'trips/{self.TRIP_ID}')
        return events

    def _stored_event_id(self):
        return self.db.collection('trips').document(self.TRIP_ID).get().to_dict().get('eventId')

    def test_insert_uses_deterministic_event_id(self):
        events = self._run()
        self.assertEqual(events.inserted[0]['id'], calendar_event_id_for_trip(self.TRIP_ID))

    def test_writes_deterministic_event_id_back_to_the_trip(self):
        self._run()
        self.assertEqual(self._stored_event_id(), calendar_event_id_for_trip(self.TRIP_ID))

    def test_duplicate_insert_adopts_existing_event_instead_of_creating_a_second(self):
        # A concurrent sync already inserted this event; Google answers 409.
        events = self._run(insert_error=_conflict_error())
        self.assertEqual(events.updated, [calendar_event_id_for_trip(self.TRIP_ID)])
        self.assertEqual(self._stored_event_id(), calendar_event_id_for_trip(self.TRIP_ID))

    def test_non_conflict_http_errors_still_propagate(self):
        server_error = HttpError(httplib2.Response({'status': 500}), b'backend error')
        with self.assertRaises(HttpError):
            self._run(insert_error=server_error)
