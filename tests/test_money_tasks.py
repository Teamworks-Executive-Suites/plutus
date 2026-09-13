import os

# Must be set before app.utils / app.firebase_setup load so `db` binds to the
# in-memory MockFirestore rather than a real Firestore client.
os.environ['TESTING'] = 'true'

from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest import TestCase  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.auto.payout_task import process_platform_payout  # noqa: E402
from app.auto.transaction_tasks import cents_from, process_transactions  # noqa: E402
from app.firebase_setup import MOCK_DB  # noqa: E402
from app.models import ActorRole, Status, TransactionType  # noqa: E402
from app.pay.tasks import calculate_fees  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()

HOST_UID = 'host_uid'
HOST_REF = f'users/{HOST_UID}'
STRIPE_ACCOUNT = 'acct_host_123'

TRANSFER_CREATE = 'app.auto.transaction_tasks.stripe.Transfer.create'
PAYOUT_CREATE = 'app.auto.payout_task.stripe.Payout.create'


def _now():
    return datetime.now(timezone.utc)


class MoneyTaskTestCase(TestCase):
    def setUp(self):
        self.db = MOCK_DB
        self.db.reset()

    def _add_host_user(self, uid=HOST_UID, stripe_account_id=STRIPE_ACCOUNT):
        self.db.collection('users').document(uid).set({'stripeAccountID': stripe_account_id})

    def _add_completed_trip(self, trip_ref, days_ago):
        self.db.collection('trips').document(trip_ref).set(
            {
                'complete': True,
                'completeDate': _now() - timedelta(days=days_ago),
            }
        )

    def _add_transaction(self, txn_id, trip_ref, **overrides):
        data = {
            'actorRef': 'users/client_uid',
            'actorRole': ActorRole.client,
            'receiverRef': HOST_REF,
            'receiverRole': ActorRole.host,
            'status': Status.in_escrow,
            'type': TransactionType.transfer,
            'tripRef': trip_ref,
            'grossFeeCents': 10000,
            'guestFeeCents': 500,
            'hostFeeCents': 9000,
            'netFeeCents': 1000,
            'refundedAmountCents': 0,
            'paymentIntentIds': [],
        }
        data.update(overrides)
        self.db.collection('transactions').document(txn_id).set(data)
        return data


class TestEscrowRelease(MoneyTaskTestCase):
    def test_releases_escrowed_host_transaction_once_trip_is_ten_days_complete(self):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1')

        transfer = MagicMock(id='tr_abc123')
        with patch(TRANSFER_CREATE, return_value=transfer) as create:
            process_transactions()

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], 9000)
        self.assertEqual(create.call_args.kwargs['destination'], STRIPE_ACCOUNT)

        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertEqual(txn['status'], Status.completed)
        self.assertEqual(txn['transferId'], 'tr_abc123')

    def test_does_not_release_before_the_ten_day_hold(self):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=3)
        self._add_transaction('txn_1', 'trip_1')

        with patch(TRANSFER_CREATE) as create:
            process_transactions()

        create.assert_not_called()
        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertEqual(txn['status'], Status.in_escrow)

    def test_eligibility_uses_call_time_not_process_start_time(self):
        """The task runs hourly in a long-lived process, so 'now' must be read per call.

        A module-level `current_time` captured at import freezes at deploy time, and every
        trip completed after that point reads as not-yet-eligible forever.
        """
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=3)
        self._add_transaction('txn_1', 'trip_1')

        transfer = MagicMock(id='tr_abc123')
        with patch(TRANSFER_CREATE, return_value=transfer) as create:
            process_transactions()
            create.assert_not_called()

            # The same long-lived process, still running a fortnight later. The hold has
            # now elapsed, which a timestamp captured at import would never notice.
            with patch('app.auto.transaction_tasks.datetime') as clock:
                clock.now.return_value = _now() + timedelta(days=14)
                process_transactions()

        create.assert_called_once()

    def test_does_not_re_transfer_a_host_transaction_that_already_settled(self):
        """A trip can carry several host transactions; only the escrowed ones may transfer."""
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_settled', 'trip_1', status=Status.completed, transferId='tr_old', hostFeeCents=4000)
        self._add_transaction('txn_escrowed', 'trip_1', hostFeeCents=9000)

        transfer = MagicMock(id='tr_new')
        with patch(TRANSFER_CREATE, return_value=transfer) as create:
            process_transactions()

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], 9000)
        settled = self.db.collection('transactions').document('txn_settled').get().to_dict()
        self.assertEqual(settled['transferId'], 'tr_old')

    def test_does_not_re_release_a_transaction_on_a_later_run(self):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1')

        transfer = MagicMock(id='tr_abc123')
        with patch(TRANSFER_CREATE, return_value=transfer) as create:
            process_transactions()
            process_transactions()

        create.assert_called_once()


class TestRefundMergeBranch(MoneyTaskTestCase):
    """A refunded trip can have no escrowed host rows left to merge.

    Production trip CY2lYiVEW4QsaJkheheO is exactly this: 3 refund transactions and 0
    in_escrow host transactions, reached through the single in_escrow row whose
    receiverRole is 'platform'. The merge branch indexes host_transactions[0]
    unconditionally, so it raises IndexError and takes the whole run down with it.
    """

    def _refunded_trip_with_no_escrowed_host_rows(self):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_platform', 'trip_1', receiverRole=ActorRole.platform)
        self._add_transaction(
            'txn_refund', 'trip_1', type=TransactionType.refund, status=Status.completed, grossFeeCents=0
        )

    def test_does_not_crash_when_there_is_nothing_left_to_merge(self):
        self._refunded_trip_with_no_escrowed_host_rows()

        with patch(TRANSFER_CREATE) as create:
            process_transactions()

        create.assert_not_called()

    def test_tolerates_missing_gross_fees_when_merging(self):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_host', 'trip_1', grossFeeCents=None)
        self._add_transaction(
            'txn_refund', 'trip_1', type=TransactionType.refund, status=Status.completed, grossFeeCents=None
        )

        transfer = MagicMock(id='tr_abc123')
        with patch(TRANSFER_CREATE, return_value=transfer):
            process_transactions()  # must not raise TypeError on None


class TestTripRefShapes(MoneyTaskTestCase):
    """`tripRef` is not the `str` that models.py declares.

    In production it is a DocumentReference on 297 of 319 transactions and a
    'trips/<id>' path string on the remaining 22. Neither can be handed to
    .document(): the first raises TypeError, the second ValueError.
    """

    def _run_escrow_with_trip_ref(self, trip_ref):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', trip_ref)

        transfer = MagicMock(id='tr_abc123')
        with patch(TRANSFER_CREATE, return_value=transfer) as create:
            process_transactions()
        return create

    def test_escrow_release_handles_a_document_reference_trip_ref(self):
        create = self._run_escrow_with_trip_ref(MOCK_DB.collection('trips').document('trip_1'))
        create.assert_called_once()

    def test_escrow_release_handles_a_path_string_trip_ref(self):
        create = self._run_escrow_with_trip_ref('trips/trip_1')
        create.assert_called_once()

    def _run_escrow_with_receiver_ref(self, receiver_ref):
        self._add_host_user()
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', receiverRef=receiver_ref)

        transfer = MagicMock(id='tr_abc123')
        with patch(TRANSFER_CREATE, return_value=transfer) as create:
            process_transactions()
        return create

    def test_escrow_release_handles_a_document_reference_receiver_ref(self):
        create = self._run_escrow_with_receiver_ref(MOCK_DB.collection('users').document(HOST_UID))
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['destination'], STRIPE_ACCOUNT)

    def test_escrow_release_handles_a_bare_id_receiver_ref(self):
        create = self._run_escrow_with_receiver_ref(HOST_UID)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['destination'], STRIPE_ACCOUNT)

    def test_escrow_release_handles_a_path_string_receiver_ref(self):
        create = self._run_escrow_with_receiver_ref(HOST_REF)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['destination'], STRIPE_ACCOUNT)


class TestPlatformOwnedEscrow(MoneyTaskTestCase):
    """The platform is its own host here, and holds no Stripe Connect account.

    113 of the 141 escrowed host transactions pay settings.platform_user_id, which has
    no stripeAccountID. Those must settle without a transfer — you do not pay yourself
    through Connect — rather than logging 'no Stripe account' forever.
    """

    PLATFORM_UID = 'platform_uid'

    def _run(self, receiver_ref):
        # A real user document with other fields but no stripeAccountID. Emphatically
        # NOT set({}): MockFirestore reports an empty document as exists=False, which
        # short-circuits the branch under test and hides the KeyError that
        # DocumentSnapshot.get raises for an absent field on a document that does exist.
        self.db.collection('users').document(self.PLATFORM_UID).set(
            {'display_name': 'Teamworks', 'isAdmin': True, 'isHost': True}
        )
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', receiverRef=receiver_ref)

        with patch.object(settings, 'platform_user_id', self.PLATFORM_UID):
            with patch(TRANSFER_CREATE) as create:
                process_transactions()
        return create

    def test_settles_without_a_transfer_when_receiver_ref_is_a_document_reference(self):
        create = self._run(MOCK_DB.collection('users').document(self.PLATFORM_UID))
        create.assert_not_called()
        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertEqual(txn['status'], Status.completed)

    def test_settles_without_a_transfer_when_receiver_ref_is_a_path_string(self):
        create = self._run(f'users/{self.PLATFORM_UID}')
        create.assert_not_called()
        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertEqual(txn['status'], Status.completed)

    def test_a_non_platform_host_without_stripe_is_left_in_escrow(self):
        create = self._run(MOCK_DB.collection('users').document('some_other_host'))
        create.assert_not_called()
        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertEqual(txn['status'], Status.in_escrow)


class TestTripRefShapesContinued(MoneyTaskTestCase):
    def _run_payout_with_trip_ref(self, trip_ref):
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', trip_ref, status=Status.completed, netFeeCents=1200)

        payout = MagicMock(id='po_abc123')
        with patch(PAYOUT_CREATE, return_value=payout) as create:
            process_platform_payout()
        return create

    def test_payout_handles_a_document_reference_trip_ref(self):
        create = self._run_payout_with_trip_ref(MOCK_DB.collection('trips').document('trip_1'))
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], 1200)

    def test_payout_handles_a_path_string_trip_ref(self):
        create = self._run_payout_with_trip_ref('trips/trip_1')
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], 1200)


class TestPlatformPayout(MoneyTaskTestCase):
    def test_pays_out_the_net_fees_of_settled_transactions(self):
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', status=Status.completed, netFeeCents=1500)

        payout = MagicMock(id='po_abc123')
        with patch(PAYOUT_CREATE, return_value=payout) as create:
            process_platform_payout()

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], 1500)

    def test_does_not_repay_transactions_already_included_in_a_payout(self):
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_completed_trip('trip_2', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', status=Status.completed, netFeeCents=1000)
        self._add_transaction('txn_2', 'trip_2', status=Status.completed, netFeeCents=2000)

        payout = MagicMock(id='po_abc123')
        with patch(PAYOUT_CREATE, return_value=payout) as create:
            process_platform_payout()
            process_platform_payout()

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], 3000)

    def test_only_pays_out_transactions_that_arrived_since_the_last_payout(self):
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', status=Status.completed, netFeeCents=1000)

        payout = MagicMock(id='po_abc123')
        with patch(PAYOUT_CREATE, return_value=payout) as create:
            process_platform_payout()

            self._add_completed_trip('trip_2', days_ago=20)
            self._add_transaction('txn_2', 'trip_2', status=Status.completed, netFeeCents=2500)
            process_platform_payout()

        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].kwargs['amount'], 1000)
        self.assertEqual(create.call_args_list[1].kwargs['amount'], 2500)

    def test_marks_included_transactions_as_paid_out(self):
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', status=Status.completed, netFeeCents=1000)

        payout = MagicMock(id='po_abc123')
        with patch(PAYOUT_CREATE, return_value=payout):
            process_platform_payout()

        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertTrue(txn['paidOut'])
        self.assertEqual(txn['payoutId'], 'po_abc123')

    def test_does_not_mark_transactions_paid_out_when_stripe_rejects_the_payout(self):
        self._add_completed_trip('trip_1', days_ago=20)
        self._add_transaction('txn_1', 'trip_1', status=Status.completed, netFeeCents=1000)

        with patch(PAYOUT_CREATE, side_effect=Exception('card_declined')):
            process_platform_payout()

        txn = self.db.collection('transactions').document('txn_1').get().to_dict()
        self.assertFalse(txn.get('paidOut', False))


class RealSnapshot:
    """A DocumentSnapshot double that behaves like the Firestore SDK's.

    MockFirestore's `.get()` returns None for a missing field. The real one
    RAISES KeyError. That difference is why `snapshot.get('x') or 0` looked
    safe in tests and killed the escrow-release run in production, so the tests
    below use this rather than the mock.
    """

    def __init__(self, data):
        self._data = dict(data)

    def to_dict(self):
        return dict(self._data)

    def get(self, field_path):
        if field_path not in self._data:
            raise KeyError(field_path)
        return self._data[field_path]


class CentsFrom(TestCase):
    def test_reads_the_field(self):
        self.assertEqual(cents_from(RealSnapshot({'grossFeeCents': 50000}), 'grossFeeCents'), 50000)

    def test_a_missing_field_is_zero_rather_than_a_crash(self):
        # The whole point. Three live refund rows written by the app carry no
        # grossFeeCents at all; `.get()` on those raises and takes the entire
        # escrow-release run with it.
        snapshot = RealSnapshot({'refundAmountCents': 25000})
        with self.assertRaises(KeyError):
            snapshot.get('grossFeeCents')
        self.assertEqual(cents_from(snapshot, 'grossFeeCents'), 0)

    def test_falls_back_to_the_other_spelling(self):
        # The app writes refundAmountCents, Plutus writes refundedAmountCents.
        app_row = RealSnapshot({'refundAmountCents': 25000})
        plutus_row = RealSnapshot({'grossFeeCents': 0, 'refundedAmountCents': 71200})
        self.assertEqual(cents_from(app_row, 'refundedAmountCents', 'refundAmountCents'), 25000)
        self.assertEqual(cents_from(plutus_row, 'refundedAmountCents', 'refundAmountCents'), 71200)

    def test_a_zero_falls_through_to_the_next_name(self):
        # Plutus writes grossFeeCents 0 AND the real figure alongside it, so a
        # zero must not be taken as the answer while another name carries money.
        row = RealSnapshot({'refundedAmountCents': 0, 'refundAmountCents': 25000})
        self.assertEqual(cents_from(row, 'refundedAmountCents', 'refundAmountCents'), 25000)

    def test_no_matching_name_is_zero(self):
        self.assertEqual(cents_from(RealSnapshot({'other': 1}), 'grossFeeCents'), 0)


class TestRefundedTripMerge(MoneyTaskTestCase):
    """A refunded booking must not pay the host the full amount.

    The merge subtracted `grossFeeCents` from the refund rows, and every refund
    row carries grossFeeCents 0 — the money is in refundedAmountCents. So the
    subtraction was always zero and the host was paid in full. One live row has
    grossFeeCents 0 against refundedAmountCents 71200.
    """

    def _add_refund(self, txn_id, trip_ref, **overrides):
        data = {
            'actorRef': 'users/platform',
            'actorRole': ActorRole.platform,
            'receiverRef': 'users/client_uid',
            'receiverRole': ActorRole.client,
            'status': Status.completed,
            'type': TransactionType.refund,
            'tripRef': trip_ref,
            'grossFeeCents': 0,
            'refundedAmountCents': 0,
        }
        data.update(overrides)
        self.db.collection('transactions').document(txn_id).set(data)

    def test_a_refund_reduces_what_the_host_is_paid(self):
        self._add_host_user()
        self._add_completed_trip('trip_r', days_ago=20)
        self._add_transaction('txn_host', 'trip_r', grossFeeCents=10000)
        # Plutus's shape: the money is in refundedAmountCents, gross is 0.
        self._add_refund('txn_refund', 'trip_r', refundedAmountCents=2500)

        with patch(TRANSFER_CREATE, return_value=MagicMock(id='tr_1')) as create:
            process_transactions()

        create.assert_called_once()
        paid = create.call_args.kwargs['amount']
        # The host's cut of 7500, not of 10000. Asserted against calculate_fees
        # rather than a hardcoded number, so the fee rate stays its business.
        #
        # An earlier version of this said `assertLess(paid, 10000)` and passed
        # WITH the bug present — the host's cut is a fraction of the total
        # either way, so the assertion could not tell 7500 from 10000. Checked
        # by restoring the bug and watching it stay green.
        self.assertEqual(paid, calculate_fees(7500)[0])
        self.assertNotEqual(paid, calculate_fees(10000)[0])
        full = self.db.collection('transactions').document('txn_host').get().to_dict()
        self.assertEqual(full['status'], Status.merged)

    def test_a_refund_written_by_the_APP_also_reduces_it(self):
        # The app spells it refundAmountCents and writes no grossFeeCents at
        # all. Three live rows look like this, and reading them with
        # DocumentSnapshot.get() raised KeyError and killed the whole run.
        self._add_host_user()
        self._add_completed_trip('trip_a', days_ago=20)
        self._add_transaction('txn_host_a', 'trip_a', grossFeeCents=10000)
        self.db.collection('transactions').document('txn_refund_a').set({
            'actorRef': 'users/platform',
            'actorRole': ActorRole.platform,
            'receiverRef': 'users/client_uid',
            'receiverRole': ActorRole.client,
            'status': Status.completed,
            'type': TransactionType.refund,
            'tripRef': 'trip_a',
            'refundAmountCents': 2500,
        })

        with patch(TRANSFER_CREATE, return_value=MagicMock(id='tr_2')) as create:
            process_transactions()

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['amount'], calculate_fees(7500)[0])

    def test_a_refund_larger_than_escrow_pays_nothing_rather_than_negative(self):
        # calculate_fees on a negative would hand Stripe a negative transfer.
        self._add_host_user()
        self._add_completed_trip('trip_big', days_ago=20)
        self._add_transaction('txn_host_big', 'trip_big', grossFeeCents=10000)
        self._add_refund('txn_refund_big', 'trip_big', refundedAmountCents=50000)

        with patch(TRANSFER_CREATE, return_value=MagicMock(id='tr_3')) as create:
            process_transactions()

        # Owed clamps to 0, so the host's cut is 0 — never a negative transfer.
        if create.called:
            self.assertEqual(create.call_args.kwargs['amount'], 0)
