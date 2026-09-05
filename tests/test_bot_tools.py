"""The checks that matter: timezone conversion, and parity with the booking page.

These are the two places a bug either double-books someone or hides a space we
could have sold. Pure functions — no network, no Firestore, no model.

The parity tests are ported case-by-case from
  lib/flutter_flow/custom_functions.dart              (slotOverlapsBooking)
  lib/components/booking_system30mins/...widget.dart  (the trips filter)
If either changes, these fail — which is the point.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.bot.tools import (
    blocks_availability,
    half_hour_slots,
    local_iso_to_utc,
    slot_overlaps_booking,
)

UTC = ZoneInfo('UTC')
DAY = (date.today() + timedelta(days=14)).isoformat()  # check_availability rejects the past
MARGIN = 30


def d(hour, minute=0):
    return datetime(2026, 9, 4, hour, minute, tzinfo=UTC)


# --- timezone -------------------------------------------------------------

def test_pst_offset():
    # January in Los Angeles is PST, UTC-8. 1pm local -> 21:00 UTC.
    assert local_iso_to_utc('2026-01-15T13:00', 'America/Los_Angeles') == datetime(2026, 1, 15, 21, tzinfo=UTC)


def test_pdt_offset():
    # July is PDT, UTC-7. Same wall clock, different instant. A static offset is
    # wrong here by an hour.
    assert local_iso_to_utc('2026-07-15T13:00', 'America/Los_Angeles') == datetime(2026, 7, 15, 20, tzinfo=UTC)


def test_dst_boundary_day():
    # 2026-03-08 is US spring-forward. 1am is still PST, 3am is PDT.
    assert local_iso_to_utc('2026-03-08T01:00', 'America/Los_Angeles') == datetime(2026, 3, 8, 9, tzinfo=UTC)
    assert local_iso_to_utc('2026-03-08T03:00', 'America/Los_Angeles') == datetime(2026, 3, 8, 10, tzinfo=UTC)


def test_rejects_tz_aware_input():
    try:
        local_iso_to_utc('2026-01-15T13:00+00:00', 'America/Los_Angeles')
    except ValueError:
        return
    raise AssertionError('should reject a tz-aware string')


# --- parity with slotOverlapsBooking --------------------------------------

def test_margin_blocks_back_to_back():
    # Booking 13:00-15:00. The 30-minute turnaround makes 12:45 and 15:15 blocked
    # even though neither is inside the booking itself.
    assert slot_overlaps_booking(d(12, 45), d(13), d(15), MARGIN)
    assert slot_overlaps_booking(d(15, 15), d(13), d(15), MARGIN)


def test_margin_edges_are_free():
    # Strict inequalities in Dart (isAfter / isBefore): exactly on the edge is free.
    assert not slot_overlaps_booking(d(12, 30), d(13), d(15), MARGIN)
    assert not slot_overlaps_booking(d(15, 30), d(13), d(15), MARGIN)


def test_inside_booking_blocked():
    assert slot_overlaps_booking(d(14), d(13), d(15), MARGIN)


def test_undated_booking_is_not_blocking():
    # Dart returns false rather than dereferencing null.
    assert not slot_overlaps_booking(d(14), None, d(15), MARGIN)
    assert not slot_overlaps_booking(d(14), d(13), None, MARGIN)


def test_half_hour_slots():
    assert half_hour_slots(d(13), d(15)) == [d(13), d(13, 30), d(14), d(14, 30), d(15)]
    assert half_hour_slots(d(13), d(13)) == [d(13)]


# --- parity with the booking page's trips filter --------------------------

def test_inquiries_do_not_block():
    # The booking page queries isInquiry == false. An unpaid inquiry must not hide
    # a space the page would happily sell.
    assert blocks_availability({'isInquiry': True, 'upcoming': True}) is False


def test_cancelled_does_not_block():
    assert blocks_availability({'cancelTrip': True, 'upcoming': True}) is False


def test_missing_cancel_field_is_not_cancelled():
    # Dart: (hasCancelTrip && !cancelTrip) || !hasCancelTrip
    assert blocks_availability({'upcoming': True}) is True


def test_requires_upcoming_external_or_blocked():
    assert blocks_availability({'upcoming': True}) is True
    assert blocks_availability({'isExternal': True}) is True
    assert blocks_availability({'isBlocked': True}) is True
    # A past, completed trip is none of the three and must not block.
    assert blocks_availability({'complete': True}) is False
    assert blocks_availability({}) is False


# --- the query bound ------------------------------------------------------
# Regression: check_availability once filtered trips with tripEndDateTime >
# start_utc. That drops a booking ending just before the requested window, so its
# 30-minute turnaround never gets applied and the bot offers a back-to-back slot
# the booking page refuses. Dart bounds on getCurrentTimestamp; so do we.

class _Snap:
    def __init__(self, data, exists=True):
        self._d, self.exists = data, exists

    def to_dict(self):
        return self._d


class _Query:
    """Records filters instead of running them; returns the trips it was given."""

    def __init__(self, trips, seen):
        self._trips, self.seen = trips, seen

    def where(self, filter):
        self.seen.append((filter.field_path, filter.op_string, filter.value))
        return self

    def get(self):
        return [_Snap(t) for t in self._trips]


class _FakeDB:
    def __init__(self, prop, trips):
        self._prop, self._trips, self.filters = prop, trips, []

    def collection(self, name):
        self._name = name
        return self

    def document(self, _id):
        return self

    def get(self):
        return _Snap(self._prop)

    def where(self, filter):
        return _Query(self._trips, self.filters).where(filter=filter)


def test_query_bounds_on_now_not_window_start(monkeypatch):
    from app.bot import tools

    # Real hours: a live property always publishes them, and check_availability now
    # refuses a window outside them before it ever queries trips.
    prop = {
        'propertyName': 'Suite 14',
        'timezone': 'America/Los_Angeles',
        'minHours': 0,
        'startTimeString': '07:00',
        'endTimeString': '20:00',
    }
    # Ends exactly when the requested window begins. Its turnaround still blocks.
    trips = [
        {
            'isInquiry': False,
            'isExternal': True,
            'tripBeginDateTime': local_iso_to_utc(f'{DAY}T09:30', 'America/Los_Angeles'),
            'tripEndDateTime': local_iso_to_utc(f'{DAY}T13:30', 'America/Los_Angeles'),
        }
    ]
    fake = _FakeDB(prop, trips)
    monkeypatch.setattr(tools, 'db', fake)

    out = tools.check_availability(['p1'], f'{DAY}T13:30', f'{DAY}T17:30')
    assert out['results'][0]['available'] is False, 'turnaround after a prior booking must block'

    # And the bound itself: whatever it is, it must not be the window start, or
    # the booking above would never have been fetched in the first place.
    bounds = [v for f, op, v in fake.filters if f == 'tripEndDateTime']
    assert bounds and bounds[0] < local_iso_to_utc(f'{DAY}T13:30', 'America/Los_Angeles')


# --- drive-time table -----------------------------------------------------

def test_area_normalisation_survives_the_ca_suffix():
    from app.bot.tools import normalize_area

    # Live Firestore holds both spellings for the same town.
    assert normalize_area('San Mateo, CA') == normalize_area('San Mateo') == 'san mateo'
    assert normalize_area('  redwood city  ') == 'redwood city'


def test_drive_minutes_known_and_unknown():
    from app.bot.tools import drive_minutes

    assert drive_minutes('Foster City', 'San Mateo, CA') == 10
    # Unknown towns return None, never a guess — the caller then says nothing.
    assert drive_minutes('Reykjavik', 'San Mateo') is None
    assert drive_minutes('Foster City', 'Atlantis') is None


# --- an impossible party size --------------------------------------------
# A guest asking for 45 when the largest space seats 25 used to be told only that
# nothing matched, so it took three more turns to learn the real ceiling. The tool
# now answers it in one — while never presenting an undersized space as fitting,
# which is the failure that puts a party in a room they do not fit in.

class _Docs(list):
    """Stands in for a Firestore query result."""


def _fake_props(*specs):
    class _Doc:
        def __init__(self, i, d):
            self.id, self._d = i, d

        def to_dict(self):
            return self._d

    return _Docs(_Doc(i, d) for i, d in specs)


def _db_returning(docs):
    class _Q:
        def where(self, filter):
            return self

        def get(self):
            return docs

    class _DB:
        def collection(self, _n):
            return _Q()

    return _DB()


def test_impossible_capacity_names_the_real_ceiling(monkeypatch):
    from app.bot import tools

    # Deliberately NOT in size order: the largest must be found by sorting, not by
    # happening to come first out of Firestore.
    docs = _fake_props(
        ('small', {'propertyName': 'Suite 103', 'propertyArea': 'San Mateo', 'maxGuests': 7,
                   'price': [59], 'isLive': True}),
        ('mid', {'propertyName': 'Suite 210', 'propertyArea': 'San Mateo', 'maxGuests': 16,
                 'price': [89], 'isLive': True}),
        ('big', {'propertyName': 'Suite 14', 'propertyArea': 'San Mateo', 'maxGuests': 25,
                 'price': [98], 'isLive': True}),
    )
    monkeypatch.setattr(tools, 'db', _db_returning(docs))

    out = tools.search_properties(45)
    assert out['properties'] == [], 'nothing seats 45, so nothing may be offered as a match'

    # The ceiling is stated, so the guest does not have to ask for it.
    assert '25' in out['note']
    alts = out['alternatives']
    assert alts and alts[0]['name'] == 'Suite 14', 'largest first'
    assert all(a['too_small_for_request'] for a in alts), 'every one must be flagged too small'


def test_a_reachable_party_size_is_not_flagged(monkeypatch):
    from app.bot import tools

    docs = _fake_props(
        ('big', {'propertyName': 'Suite 14', 'propertyArea': 'San Mateo', 'maxGuests': 25,
                 'price': [98], 'isLive': True}),
    )
    monkeypatch.setattr(tools, 'db', _db_returning(docs))

    out = tools.search_properties(10)
    assert len(out['properties']) == 1
    assert 'alternatives' not in out, 'a normal hit needs no recovery payload'


# --- test-account bookings ------------------------------------------------
# The booking flow writes to production Firestore; there is no emulator. So a
# test account's bookings are real documents, and must never take a room off sale.

def test_a_test_booking_never_blocks():
    paid_and_upcoming = {'isInquiry': False, 'upcoming': True}
    assert blocks_availability(paid_and_upcoming) is True, 'baseline: this would block'

    # Same trip, flagged as a test. Must not block, even though every other
    # condition still says it should.
    assert blocks_availability({**paid_and_upcoming, 'isTest': True}) is False
    assert blocks_availability({'isInquiry': False, 'isExternal': True, 'isTest': True}) is False
    assert blocks_availability({'isInquiry': False, 'isBlocked': True, 'isTest': True}) is False


def test_absent_is_test_still_blocks():
    # Every trip already in Firestore predates the field. Missing must mean real.
    assert blocks_availability({'isInquiry': False, 'upcoming': True}) is True
    assert blocks_availability({'isInquiry': False, 'upcoming': True, 'isTest': False}) is True


# --- the booking horizon --------------------------------------------------
# The calendar offers now .. now + 184 days. Without the same bound here, the bot
# confirms a date the booking page then refuses to show: the guest is told yes and
# finds no way to say yes back.

def test_horizon_matches_the_calendar():
    from app.bot.tools import BOOKING_HORIZON_DAYS

    # If this changes, lastDate in custom_calendar_widget2.dart and
    # kBookingHorizonDays in nav.dart must change with it.
    assert BOOKING_HORIZON_DAYS == 184


# --- opening hours --------------------------------------------------------
# The booking page can only offer slots between a property's published hours, so
# confirming 6am at a space that opens at 8am sends the guest to a calendar that
# cannot honour it. Hours differ per property — 7am at one, 8am at another.

def test_window_must_sit_inside_opening_hours():
    from app.bot.tools import within_opening_hours

    def w(a, b, opens='08:00', closes='20:00'):
        return within_opening_hours(
            datetime.fromisoformat(f'2026-09-10T{a}'),
            datetime.fromisoformat(f'2026-09-10T{b}'),
            opens,
            closes,
        )

    assert w('08:00', '12:00') is True
    # Closing time is a valid END: the Dart slot loop is inclusive of endOfDay.
    assert w('16:00', '20:00') is True
    assert w('06:00', '22:00') is False, 'the reported bug'
    assert w('07:30', '12:00') is False, 'half an hour early is still early'
    assert w('12:00', '20:30') is False, 'past closing'
    # Hours are per property.
    assert w('07:00', '11:00', opens='07:00') is True
    assert w('07:00', '11:00', opens='08:00') is False


def test_unpublished_hours_mean_unbookable_not_always_bookable():
    from app.bot.tools import parse_opening_hours

    assert parse_opening_hours({'startTimeString': '08:00', 'endTimeString': '20:00'}) == ('08:00', '20:00')
    # generateHalfHours returns [] for these, so no slot exists at any time.
    assert parse_opening_hours({'startTimeString': '', 'endTimeString': '20:00'}) is None
    assert parse_opening_hours({'startTimeString': '8am', 'endTimeString': '20:00'}) is None
    assert parse_opening_hours({}) is None


def test_friendly_hours_reads_as_speech():
    from app.bot.tools import friendly_hours

    assert friendly_hours('08:00', '20:00') == '8am to 8pm'
    assert friendly_hours('07:30', '19:45') == '7:30am to 7:45pm'


# --- search misses --------------------------------------------------------
# A name the catalogue does not have, or a price cap nothing meets, used to fall
# into the capacity-ceiling branch, which tells the model to say "nothing fits N
# guests" and give a maximum. Both answers are false when the spaces do seat N.

class _PropSnap:
    def __init__(self, id, data):
        self.id, self._d = id, data

    def to_dict(self):
        return self._d


class _CatalogueDB:
    """Just enough of the Firestore surface for search_properties."""

    def __init__(self, props):
        self._props = props

    def collection(self, _name):
        return self

    def where(self, filter):
        return self

    def get(self):
        return [_PropSnap(i, p) for i, p in self._props.items()]


CATALOGUE = {
    'p_small': {'propertyName': 'Suite 103', 'propertyArea': 'SOMA', 'maxGuests': 7, 'price': [59], 'isLive': True},
    'p_big': {'propertyName': 'Suite 14', 'propertyArea': 'SOMA', 'maxGuests': 25, 'price': [98, 128], 'isLive': True},
}


def _search(monkeypatch, **kwargs):
    from app.bot import tools

    monkeypatch.setattr(tools, 'db', _CatalogueDB(CATALOGUE))
    return tools.search_properties(**kwargs)


def test_unknown_name_does_not_claim_the_catalogue_is_too_small(monkeypatch):
    out = _search(monkeypatch, min_capacity=1, name='Suite 999')

    assert 'Say plainly that nothing fits' not in out['note']
    assert 'TOO SMALL' not in out['note']
    assert not any(a.get('too_small_for_request') for a in out['alternatives'])
    # It should hand back the real catalogue so the model can name what exists.
    assert {a['name'] for a in out['alternatives']} == {'Suite 103', 'Suite 14'}


def test_price_cap_miss_answers_with_the_real_floor(monkeypatch):
    out = _search(monkeypatch, min_capacity=4, max_hourly_price=20)

    assert 'Say plainly that nothing fits' not in out['note']
    assert out['alternatives'][0]['hourly_price_from'] == 59, 'cheapest first'
    assert '$59/hr' in out['note']


def test_a_real_capacity_miss_still_reports_the_ceiling(monkeypatch):
    out = _search(monkeypatch, min_capacity=200)

    assert 'nothing fits 200' in out['note']
    assert 'The largest space we have anywhere seats 25.' in out['note']
    assert all(a['too_small_for_request'] for a in out['alternatives'])
