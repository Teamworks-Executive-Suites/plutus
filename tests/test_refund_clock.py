"""The cancellation refund tier must be computed against the real clock.

`app/firebase_setup.py` used to expose `current_time = datetime.now(timezone.utc)` — a
module-level constant evaluated once, at import. In a long-lived uvicorn process that
freezes at deploy time, so `trip_begin_time - current_time` overstates how far away a
booking is by however long the process has been up.

That is money. With the process up nine days, a Flexible booking starting in two days
computes as eleven days out and is refunded 100% instead of 50%. The drift only ever
favours the customer, and it grows silently the longer a deploy survives.

These tests drive the real tier logic with the clock pinned, so a reintroduced frozen
timestamp fails here.
"""

import sys
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, '.')

from app.firebase_setup import MOCK_DB  # noqa: E402
from app.utils import settings  # noqa: E402

settings.testing = True

from app.pay import tasks  # noqa: E402

REAL_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
CHARGE_CENTS = 1000


class FakeCharge:
    status = 'succeeded'
    amount = CHARGE_CENTS
    amount_refunded = 0
    id = 'ch_fake'


class FakeChargeList:
    @staticmethod
    def auto_paging_iter():
        return iter([FakeCharge()])


class RefundTierUsesTheRealClock(TestCase):
    def setUp(self):
        self.db = MOCK_DB
        self.db.collection('properties').document('prop_1').set(
            {'propertyName': 'Suite A', 'cancellationPolicy': 'Flexible'}
        )
        prop_ref = self.db.collection('properties').document('prop_1').get()
        self.db.collection('trips').document('trip_1').set(
            {
                'propertyRef': prop_ref,
                'stripePaymentIntents': ['pi_fake'],
                'tripCost': 10,
                # Written onto the refund transaction once the tier is decided.
                'userRef': 'users/u1',
                'host': 'users/host_1',
            }
        )

    def _refund_for_trip_starting_in(self, delta, now=REAL_NOW):
        """Return the cents refunded for a trip starting `delta` from `now`."""
        self.db.collection('trips').document('trip_1').update({'tripBeginDateTime': now + delta})

        refunded = []
        with (
            patch.object(tasks, 'utc_now', return_value=now),
            patch.object(tasks.stripe.Charge, 'list', return_value=FakeChargeList()),
            patch.object(tasks, 'process_refund', side_effect=lambda cid, amt: refunded.append(amt)),
            patch.object(tasks, 'handle_refund'),
        ):
            tasks.process_cancel_refund('trips/trip_1', full_refund=False, actor_ref='users/u1')
        return sum(refunded)

    def test_a_booking_two_days_out_is_refunded_half_under_flexible(self):
        # Between 24 hours and 7 days -> 50%. This is the case a frozen clock got wrong:
        # a process up nine days saw eleven days and paid out in full.
        self.assertEqual(self._refund_for_trip_starting_in(timedelta(days=2)), CHARGE_CENTS // 2)

    def test_a_booking_eight_days_out_is_refunded_in_full_under_flexible(self):
        self.assertEqual(self._refund_for_trip_starting_in(timedelta(days=8)), CHARGE_CENTS)

    def test_a_booking_inside_24_hours_is_not_refunded_under_flexible(self):
        self.assertEqual(self._refund_for_trip_starting_in(timedelta(hours=6)), 0)

    def test_the_tier_moves_as_real_time_passes(self):
        """The same booking, judged at two different real times, lands in two tiers.

        A frozen module-level timestamp cannot express this: it would return the same
        tier no matter how long the process had been running.
        """
        booking_start = REAL_NOW + timedelta(days=8)

        early = self._refund_for_trip_starting_in(booking_start - REAL_NOW, now=REAL_NOW)
        # Six days later the same booking is only two days away.
        later_now = REAL_NOW + timedelta(days=6)
        late = self._refund_for_trip_starting_in(booking_start - later_now, now=later_now)

        self.assertEqual(early, CHARGE_CENTS)
        self.assertEqual(late, CHARGE_CENTS // 2)


class NoFrozenTimestampRemains(TestCase):
    def test_firebase_setup_exposes_no_module_level_current_time(self):
        """Guard against reintroduction.

        A constant here is invisible in review — it reads like any other import — and
        silently wrong only after the process has been up a while.
        """
        import app.firebase_setup as firebase_setup

        self.assertFalse(
            hasattr(firebase_setup, 'current_time'),
            'current_time is a timestamp frozen at import; use utc_now() instead',
        )
