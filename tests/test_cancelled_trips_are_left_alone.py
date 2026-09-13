"""A cancelled booking gets no reminders and is never marked complete.

Cancelling writes `cancelTrip: true` and leaves `upcoming` alone — `upcoming`
means "live", not "paid", and nothing clears it. The hourly cron filters on
`upcoming` and never looked at `cancelTrip`, so a guest who cancelled still got
"your trip is tomorrow", and after the end time the completion branch marked the
trip `complete` and asked both parties to review a stay that never happened.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

os.environ['TESTING'] = 'true'

from app.utils import settings  # noqa: E402

settings.testing = True

from app.auto.tasks import auto_complete_and_notify  # noqa: E402
from app.firebase_setup import MOCK_DB  # noqa: E402
from tests._common import enable_document_reference_equality, enable_field_filter_support  # noqa: E402

enable_field_filter_support()
enable_document_reference_equality()

SENDERS = (
    'app.auto.tasks.send_reminder_sms',
    'app.auto.tasks.send_reminder_email',
    'app.auto.tasks.complete_trip_sms',
    'app.auto.tasks.send_complete_email',
)


class CancelledTripsAreLeftAlone(TestCase):
    def setUp(self):
        self.db = MOCK_DB
        self.db.reset()
        self.db.collection('properties').document('prop_1').set(
            {'propertyName': 'Suite A', 'timezone': 'America/Los_Angeles'}
        )

    def _trip(self, doc_id, **overrides):
        now = datetime.now(timezone.utc)
        data = {
            'upcoming': True,
            'cancelTrip': True,
            'propertyRef': self.db.collection('properties').document('prop_1'),
            'tripBeginDateTime': now - timedelta(hours=4),
            'tripEndDateTime': now - timedelta(hours=1),
        }
        data.update(overrides)
        self.db.collection('trips').document(doc_id).set(data)

    def _run(self):
        patches = [patch(p) for p in SENDERS]
        started = [p.start() for p in patches]
        try:
            auto_complete_and_notify()
        finally:
            for p in patches:
                p.stop()
        return dict(zip(SENDERS, started))

    def test_a_cancelled_past_trip_is_not_marked_complete(self):
        self._trip('trip_cancelled')
        self._run()
        after = self.db.collection('trips').document('trip_cancelled').get().to_dict()
        self.assertNotEqual(
            after.get('complete'),
            True,
            'a cancelled booking must not be completed, or both parties are '
            'asked to review a stay that never happened',
        )

    def test_a_cancelled_past_trip_sends_nothing(self):
        self._trip('trip_cancelled')
        sent = self._run()
        for name, mock in sent.items():
            self.assertEqual(mock.call_count, 0, f'{name} fired for a cancelled trip')

    def test_a_cancelled_FUTURE_trip_gets_no_reminder(self):
        now = datetime.now(timezone.utc)
        self._trip(
            'trip_tomorrow',
            tripBeginDateTime=now + timedelta(hours=24),
            tripEndDateTime=now + timedelta(hours=28),
        )
        sent = self._run()
        self.assertEqual(sent['app.auto.tasks.send_reminder_sms'].call_count, 0)
        self.assertEqual(sent['app.auto.tasks.send_reminder_email'].call_count, 0)

    def test_a_LIVE_past_trip_is_still_completed(self):
        # The guard must not have turned the whole job off.
        self._trip('trip_live', cancelTrip=False)
        self._run()
        after = self.db.collection('trips').document('trip_live').get().to_dict()
        self.assertEqual(after.get('complete'), True)

    def test_a_trip_with_no_cancelTrip_field_is_still_completed(self):
        # Absent means not cancelled. Written before the flag existed.
        now = datetime.now(timezone.utc)
        self.db.collection('trips').document('trip_legacy').set(
            {
                'upcoming': True,
                'propertyRef': self.db.collection('properties').document('prop_1'),
                'tripBeginDateTime': now - timedelta(hours=4),
                'tripEndDateTime': now - timedelta(hours=1),
            }
        )
        self._run()
        after = self.db.collection('trips').document('trip_legacy').get().to_dict()
        self.assertEqual(after.get('complete'), True)


class RemindersSendOnce(TestCase):
    """A reminder goes out once, however often the cron runs.

    The 24-hour window is TWO HOURS wide (23h to 25h) on an HOURLY cron, so a
    trip sits inside it on two consecutive runs and both parties were texted
    and emailed twice. The 1-hour window is exactly the cadence, so it fires
    once when the schedule is punctual and twice when it drifts.

    Widening or narrowing the window only moves the problem: one that cannot
    double-fire also cannot survive a missed run. What fixes it is remembering.
    """

    def setUp(self):
        self.db = MOCK_DB
        self.db.reset()
        self.db.collection('properties').document('prop_1').set(
            {'propertyName': 'Suite A', 'timezone': 'America/Los_Angeles'}
        )

    def _trip_starting_in(self, doc_id, delta):
        now = datetime.now(timezone.utc)
        self.db.collection('trips').document(doc_id).set(
            {
                'upcoming': True,
                'cancelTrip': False,
                'propertyRef': self.db.collection('properties').document('prop_1'),
                'tripBeginDateTime': now + delta,
                'tripEndDateTime': now + delta + timedelta(hours=4),
            }
        )

    def _run(self):
        patches = [patch(p) for p in SENDERS]
        started = [p.start() for p in patches]
        try:
            auto_complete_and_notify()
        finally:
            for p in patches:
                p.stop()
        return dict(zip(SENDERS, started))

    def test_two_runs_inside_the_24h_window_send_one_reminder(self):
        # 24h exactly: inside the 23h-25h window on this run and the next.
        self._trip_starting_in('trip_24', timedelta(hours=24))
        first = self._run()
        self.assertEqual(first['app.auto.tasks.send_reminder_sms'].call_count, 1)
        second = self._run()
        self.assertEqual(
            second['app.auto.tasks.send_reminder_sms'].call_count,
            0,
            'the second run inside the same window must not remind again',
        )

    def test_the_trip_records_which_reminder_went_out(self):
        self._trip_starting_in('trip_24', timedelta(hours=24))
        self._run()
        after = self.db.collection('trips').document('trip_24').get().to_dict()
        self.assertIn('24h', after.get('remindersSent') or [])

    def test_the_1h_reminder_is_tracked_separately(self):
        # Having had the 24h one must not suppress the 1h one.
        self._trip_starting_in('trip_1h', timedelta(hours=1))
        self.db.collection('trips').document('trip_1h').update({'remindersSent': ['24h']})
        sent = self._run()
        self.assertEqual(sent['app.auto.tasks.send_reminder_sms'].call_count, 1)
        after = self.db.collection('trips').document('trip_1h').get().to_dict()
        self.assertIn('1h', after.get('remindersSent') or [])

    def test_a_trip_with_no_remindersSent_field_still_gets_one(self):
        # Absent means none sent. Every trip written before this existed.
        self._trip_starting_in('trip_legacy', timedelta(hours=24))
        sent = self._run()
        self.assertEqual(sent['app.auto.tasks.send_reminder_sms'].call_count, 1)
