"""A ledger failure AFTER the card is charged must not look like "try again".

Everything inside the inner try of `process_extra_charge` runs after
`stripe.PaymentIntent.create(..., confirm=True)` has succeeded, the dispute has
been marked completed, and the intent has been appended to the trip. Only the
ledger rows can fail there.

That handler used to overwrite the dispute back to `status: 'failed'` and answer
500. Both lie in the direction that costs money: the dispute says no charge
happened when one has, and a 500 is what the app shows the host as "try again" —
so the guest's card is charged a second time for the same damage, and the first
charge is invisible because its own dispute says failed.

The extra-charge tests in test_stripe.py are commented out in their entirety,
which is why this went unnoticed.
"""

import os

os.environ['TESTING'] = 'true'

from unittest import TestCase  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.firebase_setup import MOCK_DB  # noqa: E402
from app.pay.tasks import process_extra_charge  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()

TRIP = 'trips/trip_xc'
DISPUTE = 'disputes/dispute_xc'
ACTOR = 'users/host_xc'


class ExtraChargePostChargeFailure(TestCase):
    def setUp(self):
        self.db = MOCK_DB
        self.db.reset()
        self.db.collection('trips').document('trip_xc').set(
            {
                'stripePaymentIntents': ['pi_original'],
                'userRef': self.db.collection('users').document('guest_xc'),
                'propertyRef': self.db.collection('properties').document('prop_xc'),
            }
        )
        self.db.collection('disputes').document('dispute_xc').set(
            {'disputeAmount': 250.0, 'status': 'pending', 'disputeDescription': 'Broken chair'}
        )
        self.db.collection('users').document('guest_xc').set({'email': 'guest@example.com'})
        self.db.collection('properties').document('prop_xc').set(
            {'userRef': self.db.collection('users').document('host_xc')}
        )
        self.db.collection('users').document('host_xc').set({'email': 'host@example.com'})

    def _charge_succeeds(self):
        """Stripe takes the money; the ledger write is what blows up."""
        original = MagicMock(customer='cus_1', payment_method='pm_1')
        charged = MagicMock(id='pi_extra_charge')
        return (
            patch('app.pay.tasks.stripe.PaymentIntent.retrieve', return_value=original),
            patch('app.pay.tasks.stripe.PaymentIntent.create', return_value=charged),
            patch('app.pay.tasks.Transaction', side_effect=RuntimeError('firestore unavailable')),
        )

    def test_the_dispute_stays_completed_because_the_charge_happened(self):
        retrieve, create, ledger = self._charge_succeeds()
        with retrieve, create, ledger:
            process_extra_charge(TRIP, DISPUTE, ACTOR)

        dispute = self.db.collection('disputes').document('dispute_xc').get().to_dict()
        self.assertEqual(
            dispute['status'],
            'completed',
            'the card was charged, so marking the dispute failed tells the host '
            'to raise it again and charges the guest twice',
        )

    def test_it_does_not_answer_with_an_error_the_app_reads_as_retry(self):
        retrieve, create, ledger = self._charge_succeeds()
        with retrieve, create, ledger:
            response = process_extra_charge(TRIP, DISPUTE, ACTOR)

        self.assertNotEqual(response['status'], 500)
        self.assertEqual(response['status'], 200)

    def test_it_says_plainly_that_the_ledger_is_incomplete(self):
        retrieve, create, ledger = self._charge_succeeds()
        with retrieve, create, ledger:
            response = process_extra_charge(TRIP, DISPUTE, ACTOR)

        self.assertTrue(response['details'].get('ledger_incomplete'))
        self.assertIn('do not retry', response['message'].lower())

    def test_the_payment_intent_is_reported_so_the_row_can_be_repaired(self):
        retrieve, create, ledger = self._charge_succeeds()
        with retrieve, create, ledger:
            response = process_extra_charge(TRIP, DISPUTE, ACTOR)

        self.assertEqual(response['details']['payment_intent'].id, 'pi_extra_charge')
