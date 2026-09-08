"""Off-session ("book directly on behalf") payment-method resolution.

The bug this pins: `process_off_session_payment` read only
`customer.invoice_settings.default_payment_method` and returned
"No payment method on file" when it was empty. Attaching a card during the
ordinary PaymentSheet checkout does NOT set that field — it is a separate,
explicit setting nothing in the app ever wrote — so the default was
effectively always empty and book-directly failed for every real guest,
while ordinary booking (which charges the attached PaymentMethod directly)
worked. A host reported exactly this: "she has her credit card in the system
and used it to book her last office", yet book-directly said no method on
file.

The fix falls back to the customer's most-recently-attached card. These tests
mock Stripe entirely (no STRIPE_SECRET_KEY, unlike test_stripe.py) so they run
in CI.
"""

import os

os.environ['TESTING'] = 'true'

from unittest import TestCase  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from app.utils import settings  # noqa: E402

settings.testing = True

from app.pay.tasks import process_off_session_payment  # noqa: E402

CUSTOMER_LIST = 'app.pay.tasks.stripe.Customer.list'
PM_LIST = 'app.pay.tasks.stripe.PaymentMethod.list'
PI_CREATE = 'app.pay.tasks.stripe.PaymentIntent.create'


def _customer(cid='cus_123', default_pm=None):
    c = MagicMock(id=cid)
    c.invoice_settings.default_payment_method = default_pm
    return c


def _list(items):
    """A stripe ListObject stand-in: has `.data`."""
    return MagicMock(data=list(items))


class OffSessionPaymentMethodTest(TestCase):
    def _run(self):
        return process_off_session_payment(
            customer_id='guest@example.com',
            amount=28600,
            currency='usd',
            trip_ref='trips/fake',
            guest_email='guest@example.com',
        )

    def test_uses_the_invoice_default_when_set(self):
        # Unchanged behaviour: an explicit default is still preferred, and the
        # attached-card fallback is not even consulted.
        with patch(CUSTOMER_LIST, return_value=_list([_customer(default_pm='pm_default')])), \
                patch(PM_LIST) as pm_list, \
                patch(PI_CREATE, return_value=MagicMock(id='pi_1', status='succeeded')) as create:
            result = self._run()

        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['paymentIntentId'], 'pi_1')
        pm_list.assert_not_called()
        self.assertEqual(create.call_args.kwargs['payment_method'], 'pm_default')

    def test_falls_back_to_the_attached_card_when_no_default(self):
        # The regression case: no invoice-settings default, but a card is
        # attached (what checkout leaves behind). This used to fail with
        # "No payment method on file"; now it charges the attached card.
        newest = MagicMock()
        newest.id = 'pm_newest'
        older = MagicMock()
        older.id = 'pm_older'
        with patch(CUSTOMER_LIST, return_value=_list([_customer(default_pm=None)])), \
                patch(PM_LIST, return_value=_list([newest, older])) as pm_list, \
                patch(PI_CREATE, return_value=MagicMock(id='pi_2', status='succeeded')) as create:
            result = self._run()

        self.assertEqual(result['status'], 'succeeded')
        pm_list.assert_called_once()
        # Stripe returns cards newest-first; the most recent is charged.
        self.assertEqual(create.call_args.kwargs['payment_method'], 'pm_newest')
        self.assertTrue(create.call_args.kwargs['off_session'])

    def test_no_customer_still_reports_no_method(self):
        with patch(CUSTOMER_LIST, return_value=_list([])), \
                patch(PI_CREATE) as create:
            result = self._run()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'No payment method on file')
        create.assert_not_called()

    def test_customer_but_genuinely_no_card_reports_no_method(self):
        # Customer exists, no default, and no attached cards either — the
        # message is honest here, and no charge is attempted.
        with patch(CUSTOMER_LIST, return_value=_list([_customer(default_pm=None)])), \
                patch(PM_LIST, return_value=_list([])), \
                patch(PI_CREATE) as create:
            result = self._run()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'No payment method on file')
        create.assert_not_called()
