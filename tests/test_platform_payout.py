import os

# Must be set before app.utils / app.firebase_setup load so `db` binds to MockFirestore.
os.environ['TESTING'] = 'true'

from unittest import TestCase  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.auto import payout_task  # noqa: E402
from app.firebase_setup import MOCK_DB  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()


class TestPlatformPayoutSelection(TestCase):
    """Which ledger rows the hourly bank sweep is allowed to count.

    It selected `status != in_escrow`, which admitted rows that are not owed to
    anyone — `merged` (escrow a refund folded into a replacement, still holding
    its PRE-refund netFeeCents) and `failed` (money that never moved) — and,
    because `!=` skips documents missing the field, silently excluded rows
    written without a status at all.
    """

    def setUp(self):
        MOCK_DB.reset()
        for i in (1, 2, 3, 4, 5):
            MOCK_DB.collection('trips').document(f'trip_{i}').set({'complete': True})

    def _row(self, doc_id, status, cents, trip):
        data = {
            'netFeeCents': cents,
            'tripRef': MOCK_DB.collection('trips').document(trip),
        }
        if status is not None:
            data['status'] = status
        MOCK_DB.collection('transactions').document(doc_id).set(data)

    def _sweep(self):
        created = {}

        class FakePayout:
            id = 'po_test'

        def capture(**kwargs):
            created.update(kwargs)
            return FakePayout()

        with patch.object(payout_task.stripe.Payout, 'create', capture):
            payout_task.process_platform_payout()
        return created.get('amount')

    def test_counts_only_completed_rows(self):
        self._row('t1', 'completed', 1000, 'trip_1')
        self._row('t2', 'merged', 5000, 'trip_2')
        self._row('t3', 'failed', 7000, 'trip_3')
        self._row('t4', 'in_escrow', 9000, 'trip_4')
        # A row with NO status at all — invisible to the old `!=` filter.
        self._row('t5', None, 3000, 'trip_5')

        # Only the completed row is the platform's to sweep.
        self.assertEqual(self._sweep(), 1000)

    def test_a_merged_row_never_contributes_its_stale_amount(self):
        # The exact mis-pick: a refunded trip's original escrow row still holds
        # the pre-refund figure, and the per-trip dedup meant it could win.
        self._row('stale', 'merged', 50000, 'trip_1')
        self._row('real', 'completed', 100, 'trip_1')
        self.assertEqual(self._sweep(), 100)

    def test_nothing_payable_creates_no_payout(self):
        self._row('t1', 'merged', 5000, 'trip_1')
        self._row('t2', 'failed', 7000, 'trip_2')
        self.assertIsNone(self._sweep())

    def test_already_paid_rows_are_not_swept_twice(self):
        self._row('t1', 'completed', 1000, 'trip_1')
        MOCK_DB.collection('transactions').document('t1').update({'paidOut': True})
        self.assertIsNone(self._sweep())
