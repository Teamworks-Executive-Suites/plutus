import os

# Must be set before app.utils / app.firebase_setup load so `db` binds to MockFirestore.
os.environ['TESTING'] = 'true'

from unittest import TestCase  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.firebase_setup import MOCK_DB  # noqa: E402
from app.pay.tasks import resolve_host_user_ref  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()

HOST_UID = 'host_uid'
GUEST_UID = 'guest_uid'
PROPERTY_ID = 'property_1'


class TestResolveHostUserRef(TestCase):
    """The extra-charge host transfer addressed a *property* id, which is not a user.

    `receiverRef=trip.get('propertyRef').id` put a 20-character Firestore auto-id into a
    field every consumer reads as `users/<uid>`, leaving transactions pointing at
    receivers that have no user document at all.
    """

    def setUp(self):
        self.db = MOCK_DB
        self.db.reset()
        self.db.collection('users').document(HOST_UID).set({'isHost': True})
        self.db.collection('properties').document(PROPERTY_ID).set(
            {'userRef': self.db.collection('users').document(HOST_UID)}
        )

    def _trip(self, **fields):
        self.db.collection('trips').document('trip_1').set(fields)
        return self.db.collection('trips').document('trip_1').get()

    def test_resolves_the_property_owner_not_the_property(self):
        trip = self._trip(propertyRef=self.db.collection('properties').document(PROPERTY_ID))
        self.assertEqual(resolve_host_user_ref(trip), f'users/{HOST_UID}')

    def test_resolves_a_property_ref_stored_as_a_path_string(self):
        trip = self._trip(propertyRef=f'properties/{PROPERTY_ID}')
        self.assertEqual(resolve_host_user_ref(trip), f'users/{HOST_UID}')

    def test_never_returns_the_guest_who_booked(self):
        trip = self._trip(
            propertyRef=self.db.collection('properties').document(PROPERTY_ID),
            userRef=self.db.collection('users').document(GUEST_UID),
        )
        self.assertNotEqual(resolve_host_user_ref(trip), f'users/{GUEST_UID}')

    def test_falls_back_to_the_denormalised_host_field(self):
        trip = self._trip(host=self.db.collection('users').document(HOST_UID))
        self.assertEqual(resolve_host_user_ref(trip), f'users/{HOST_UID}')

    def test_prefers_the_property_owner_over_a_stale_host_field(self):
        trip = self._trip(
            propertyRef=self.db.collection('properties').document(PROPERTY_ID),
            host=self.db.collection('users').document('stale_uid'),
        )
        self.assertEqual(resolve_host_user_ref(trip), f'users/{HOST_UID}')

    def test_returns_none_when_the_host_cannot_be_determined(self):
        trip = self._trip(userRef=self.db.collection('users').document(GUEST_UID))
        self.assertIsNone(resolve_host_user_ref(trip))

    def test_returns_none_when_the_property_is_missing(self):
        trip = self._trip(propertyRef='properties/does_not_exist')
        self.assertIsNone(resolve_host_user_ref(trip))
