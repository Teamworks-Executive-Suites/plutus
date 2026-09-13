"""A booking email says the time the guest will actually turn up.

Trip times are stored UTC and the property's IANA zone lives on the property.
The template f-stringed the raw value, so a 9:00 AM Los Angeles booking arrived
in both inboxes as `2026-07-15 16:00:00+00:00` — seven hours out, in a format
nobody reads, on the one email that tells someone when to be somewhere.
"""

import os
from datetime import datetime, timezone
from unittest import TestCase

os.environ['TESTING'] = 'true'

from app.auto.tasks import local_time_for_email  # noqa: E402

LA = 'America/Los_Angeles'
UTC_9AM_LA_SUMMER = datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc)


class LocalTimeForEmail(TestCase):
    def test_a_utc_instant_renders_in_the_property_zone(self):
        out = local_time_for_email(UTC_9AM_LA_SUMMER, LA)
        self.assertIn('09:00 AM', out)
        self.assertIn('15 Jul 2026', out)

    def test_it_does_not_leak_the_raw_utc_form(self):
        out = local_time_for_email(UTC_9AM_LA_SUMMER, LA)
        self.assertNotIn('+00:00', out)
        self.assertNotIn('16:00', out)

    def test_the_zone_actually_matters(self):
        # Same instant, two properties, two different local times.
        la = local_time_for_email(UTC_9AM_LA_SUMMER, LA)
        nyc = local_time_for_email(UTC_9AM_LA_SUMMER, 'America/New_York')
        self.assertNotEqual(la, nyc)
        self.assertIn('12:00 PM', nyc)

    def test_winter_and_summer_differ_by_the_dst_offset(self):
        # 17:00Z is 9:00 AM in LA in January, 10:00 AM in July.
        jan = local_time_for_email(datetime(2026, 1, 15, 17, 0, tzinfo=timezone.utc), LA)
        jul = local_time_for_email(datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc), LA)
        self.assertIn('09:00 AM', jan)
        self.assertIn('10:00 AM', jul)

    def test_a_missing_time_is_empty_rather_than_the_word_None(self):
        self.assertEqual(local_time_for_email(None, LA), '')

    def test_a_missing_zone_falls_back_instead_of_raising(self):
        # An ugly time beats no email; this runs after the booking is made.
        out = local_time_for_email(UTC_9AM_LA_SUMMER, None)
        self.assertIn('2026', out)

    def test_a_nonsense_zone_falls_back_instead_of_raising(self):
        out = local_time_for_email(UTC_9AM_LA_SUMMER, 'Not/AZone')
        self.assertIn('2026', out)
