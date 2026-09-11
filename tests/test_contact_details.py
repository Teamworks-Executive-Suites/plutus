import os

# Must be set before app.utils / app.firebase_setup load so `db` binds to MockFirestore.
os.environ['TESTING'] = 'true'

from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest import TestCase  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.auto import tasks  # noqa: E402
from app.auto.tasks import get_contact_details  # noqa: E402
from app.firebase_setup import MOCK_DB  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()

GUEST_UID = 'guest_uid'
HOST_UID = 'host_uid'


class TestGetContactDetails(TestCase):
    """Who gets the SMS, resolved from ref fields that hold three shapes.

    `get_contact_details` read the two refs with two different assumptions in
    the same function: `property_doc.get('userRef').id` treats the value as a
    DocumentReference, while `db.collection('users').document(trip_doc.get('userRef'))`
    passes it straight in as a document id — which is a string.

    The Flutter app writes `trips.userRef` as a DocumentReference
    (`trips_record.dart:26`), so that second line raised
    `ValueError: A path element must be a string` on every app-written trip.

    The blast radius was wider than the SMS. In the completion cron the SMS and
    the completion EMAIL share one try block, so the raise took the email with
    it and logged 'Failed to complete trip' for a trip that had completed fine.
    """

    def setUp(self):
        MOCK_DB.reset()
        MOCK_DB.collection('users').document(HOST_UID).set(
            {'smsOptIn': True, 'phone_numbers': ['+15550000001', '+15550000002']}
        )
        MOCK_DB.collection('users').document(GUEST_UID).set(
            {'smsOptIn': True, 'phone_numbers': ['+15550000003']}
        )

    def _docs(self, trip_user_ref, property_user_ref):
        MOCK_DB.collection('properties').document('prop_1').set({'userRef': property_user_ref})
        MOCK_DB.collection('trips').document('trip_1').set({'userRef': trip_user_ref})
        return (
            MOCK_DB.collection('trips').document('trip_1').get(),
            MOCK_DB.collection('properties').document('prop_1').get(),
        )

    def test_both_refs_as_document_references(self):
        """What the Flutter app writes. This raised ValueError before the fix."""
        trip, prop = self._docs(
            MOCK_DB.collection('users').document(GUEST_UID),
            MOCK_DB.collection('users').document(HOST_UID),
        )
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertEqual(host_numbers, ['+15550000001', '+15550000002'])
        self.assertEqual(guest_number, '+15550000003')

    def test_both_refs_as_path_strings(self):
        """What Plutus itself writes elsewhere: 'users/<uid>'."""
        trip, prop = self._docs(f'users/{GUEST_UID}', f'users/{HOST_UID}')
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertEqual(host_numbers, ['+15550000001', '+15550000002'])
        self.assertEqual(guest_number, '+15550000003')

    def test_mixed_shapes(self):
        """The shapes are per-field, not per-document — they really do mix."""
        trip, prop = self._docs(
            f'users/{GUEST_UID}',
            MOCK_DB.collection('users').document(HOST_UID),
        )
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertEqual(host_numbers, ['+15550000001', '+15550000002'])
        self.assertEqual(guest_number, '+15550000003')

    def test_bare_id(self):
        """The third shape `document_id` knows about."""
        trip, prop = self._docs(GUEST_UID, HOST_UID)
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertEqual(guest_number, '+15550000003')

    def test_opted_out_users_get_no_number(self):
        """smsOptIn gates the number, and must keep doing so after the fix."""
        MOCK_DB.collection('users').document(GUEST_UID).set(
            {'smsOptIn': False, 'phone_numbers': ['+15550000003']}
        )
        trip, prop = self._docs(f'users/{GUEST_UID}', f'users/{HOST_UID}')
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertEqual(host_numbers, ['+15550000001', '+15550000002'])
        self.assertIsNone(guest_number)

    def test_missing_ref_does_not_raise(self):
        """An absent ref returns no contact rather than exploding the cron."""
        trip, prop = self._docs(None, f'users/{HOST_UID}')
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertIsNone(guest_number)


class StrictSnapshot:
    """A DocumentSnapshot that behaves like the REAL client, not the mock.

    `DocumentSnapshot.get()` raises KeyError when the field is absent
    (`field_path.get_nested_value`), while MockFirestore returns None. That
    difference is not cosmetic: 34 of 40 live trips have no `userRef` at all,
    because the booking funnel writes a draft before anyone signs in. A test
    written against the mock's leniency passes on code that raises in
    production — which is exactly what happened to the first version of this
    suite.
    """

    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = None

    def to_dict(self):
        return dict(self._data)

    def get(self, field_path):
        if field_path not in self._data:
            raise KeyError(f"'{field_path}' is not contained in the data")
        return self._data[field_path]

    @property
    def exists(self):
        return True


class TestAbsentRefsAgainstRealSnapshotBehaviour(TestCase):
    """Neither notification function may reach for a possibly-absent field
    with `.get()`. Both must read through `to_dict()`."""

    def setUp(self):
        MOCK_DB.reset()
        MOCK_DB.collection('users').document(HOST_UID).set(
            {'smsOptIn': True, 'phone_numbers': ['+15550000001'], 'email': 'host@example.com'}
        )

    def test_sms_survives_a_trip_with_no_userRef(self):
        trip = StrictSnapshot('trip_1', {'tripBeginDateTime': None})
        prop = StrictSnapshot('prop_1', {'userRef': f'users/{HOST_UID}'})
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertIsNone(guest_number)

    def test_email_survives_a_trip_with_no_userRef(self):
        trip = StrictSnapshot('trip_1', {})
        prop = StrictSnapshot('prop_1', {'userRef': f'users/{HOST_UID}'})

        def explode(*_a, **_k):
            raise AssertionError('should not have tried to send')

        with patch.object(tasks.requests, 'post', explode):
            tasks.sendgrid_email(trip, prop, 'template-1', to_host=True)

    def test_sms_survives_a_property_with_no_userRef(self):
        trip = StrictSnapshot('trip_1', {'userRef': f'users/{GUEST_UID}'})
        prop = StrictSnapshot('prop_1', {})
        host_numbers, guest_number = get_contact_details(trip, prop)
        self.assertIsNone(host_numbers)


class TestCompletionNotificationIsolation(TestCase):
    """A trip's completion email must not depend on its SMS succeeding.

    They shared one try block, so any raise inside the SMS — and
    `get_contact_details` raised on every app-written trip — skipped the email
    too, and logged the trip as failed to complete when it had not failed.
    """

    def setUp(self):
        MOCK_DB.reset()
        MOCK_DB.collection('users').document(HOST_UID).set(
            {'smsOptIn': True, 'phone_numbers': ['+15550000001']}
        )
        MOCK_DB.collection('users').document(GUEST_UID).set(
            {'smsOptIn': True, 'phone_numbers': ['+15550000003']}
        )
        prop = MOCK_DB.collection('properties').document('prop_1')
        prop.set({'userRef': f'users/{HOST_UID}', 'timezone': 'America/Los_Angeles'})
        MOCK_DB.collection('trips').document('trip_1').set(
            {
                'userRef': f'users/{GUEST_UID}',
                'propertyRef': prop,
                'upcoming': True,
                'complete': False,
                'tripBeginDateTime': datetime.now(timezone.utc) - timedelta(hours=4),
                'tripEndDateTime': datetime.now(timezone.utc) - timedelta(hours=2),
            }
        )

    def test_a_failing_sms_still_lets_the_email_send(self):
        sent = {'email': False}

        def boom(*_args, **_kwargs):
            raise RuntimeError('twilio is down')

        def record_email(*_args, **_kwargs):
            sent['email'] = True

        with patch.object(tasks, 'complete_trip_sms', boom), patch.object(
            tasks, 'send_complete_email', record_email
        ):
            tasks.auto_complete_and_notify()

        self.assertTrue(sent['email'], 'the email was skipped because the SMS raised')
        trip = MOCK_DB.collection('trips').document('trip_1').get()
        self.assertTrue(trip.get('complete'), 'the trip should still be marked complete')



class TestEmailRefShapes(TestCase):
    """The email path had the identical split assumption as the SMS path.

    `sendgrid_email` read `property_doc.get('userRef').id` on one line and
    passed `trip_doc.get('userRef')` straight to `.document()` on the next, so
    it failed on exactly the trips the SMS failed on. Both notification
    channels were broken by one mistake written twice.
    """

    def setUp(self):
        MOCK_DB.reset()
        MOCK_DB.collection('users').document(HOST_UID).set(
            {'email': 'host@example.com', 'display_name': 'Hosty'}
        )
        MOCK_DB.collection('users').document(GUEST_UID).set(
            {'email': 'guest@example.com', 'display_name': 'Guesty'}
        )

    def _docs(self, trip_user_ref, property_user_ref):
        MOCK_DB.collection('properties').document('prop_1').set(
            {
                'userRef': property_user_ref,
                'propertyName': 'Suite 103',
                'mainImage': ['https://example.com/a.jpg'],
                'cleaningFee': 50,
            }
        )
        MOCK_DB.collection('trips').document('trip_1').set(
            {
                'userRef': trip_user_ref,
                'tripBeginDateTime': datetime.now(timezone.utc),
                'tripEndDateTime': datetime.now(timezone.utc),
                'tripBaseTotal': 100,
                'tripAddonTotal': 0,
                'tripCost': 150,
            }
        )
        return (
            MOCK_DB.collection('trips').document('trip_1').get(),
            MOCK_DB.collection('properties').document('prop_1').get(),
        )

    def _addressee(self, trip_user_ref, property_user_ref, to_host):
        seen = {}

        class FakeResponse:
            text = 'ok'

        def capture(url, headers=None, json=None):
            seen['to'] = json['personalizations'][0]['to'][0]['email']
            return FakeResponse()

        trip, prop = self._docs(trip_user_ref, property_user_ref)
        with patch.object(tasks.requests, 'post', capture):
            tasks.sendgrid_email(trip, prop, 'template-1', to_host=to_host)
        return seen.get('to')

    def test_document_references_address_the_right_people(self):
        """What the Flutter app writes. This raised before the fix."""
        trip_ref = MOCK_DB.collection('users').document(GUEST_UID)
        prop_ref = MOCK_DB.collection('users').document(HOST_UID)
        self.assertEqual(self._addressee(trip_ref, prop_ref, to_host=True), 'host@example.com')
        self.assertEqual(self._addressee(trip_ref, prop_ref, to_host=False), 'guest@example.com')

    def test_path_strings_address_the_right_people(self):
        self.assertEqual(
            self._addressee(f'users/{GUEST_UID}', f'users/{HOST_UID}', to_host=True),
            'host@example.com',
        )
        self.assertEqual(
            self._addressee(f'users/{GUEST_UID}', f'users/{HOST_UID}', to_host=False),
            'guest@example.com',
        )

    def test_an_unresolvable_ref_sends_nothing_rather_than_emailing_none(self):
        self.assertIsNone(self._addressee(None, f'users/{HOST_UID}', to_host=True))
