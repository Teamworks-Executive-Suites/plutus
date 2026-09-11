import os

# Must be set before app.utils / app.firebase_setup load so `db` binds to MockFirestore.
os.environ['TESTING'] = 'true'

from unittest import TestCase  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.firebase_setup import MOCK_DB  # noqa: E402
from app.pay.tasks import user_ref_path  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()

GUEST_UID = 'guest_uid'


class TestUserRefPath(TestCase):
    """Ledger ref fields are declared `str` and the ledger is read by matching on
    them, so what is written has to be ONE predictable shape.

    Two call sites were not. One interpolated a DocumentReference object into an
    f-string, storing 'users/' followed by its repr. The other stored a bare id
    with no prefix. Neither matches any query of any shape — `transaction_tasks`
    logs 'unusable receiverRef, skipping' and passes the row over, which for a
    host-side transfer means the host is never paid for it.
    """

    def test_normalises_a_bare_uid(self):
        self.assertEqual(user_ref_path(GUEST_UID), f'users/{GUEST_UID}')

    def test_normalises_a_path_string(self):
        self.assertEqual(user_ref_path(f'users/{GUEST_UID}'), f'users/{GUEST_UID}')

    def test_normalises_a_document_reference(self):
        # The shape that produced 'users/<DocumentReference object at 0x...>'.
        ref = MOCK_DB.collection('users').document(GUEST_UID)
        self.assertEqual(user_ref_path(ref), f'users/{GUEST_UID}')

    def test_never_embeds_a_repr(self):
        ref = MOCK_DB.collection('users').document(GUEST_UID)
        self.assertNotIn('object at', user_ref_path(ref))
        self.assertNotIn('<', user_ref_path(ref))

    def test_is_idempotent(self):
        once = user_ref_path(GUEST_UID)
        self.assertEqual(user_ref_path(once), once)

    def test_unresolvable_is_empty_rather_than_a_crash(self):
        # These rows are written AFTER Stripe has moved the money. Raising
        # there would leave the refund done with no ledger row at all, which is
        # worse than a row the reader skips.
        self.assertEqual(user_ref_path(None), '')
        self.assertEqual(user_ref_path(''), '')

    def test_unresolvable_is_not_mistakable_for_a_path(self):
        # The old code wrote 'users/' for a missing id, which LOOKS like a
        # path and resolves to nothing.
        self.assertNotEqual(user_ref_path(None), 'users/')
