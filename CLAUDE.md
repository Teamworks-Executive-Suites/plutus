# Plutus — Teamworks Backend

FastAPI backend for the Teamworks booking platform. Handles payments, Google Calendar sync, and scheduled automation.

## Stack

- **FastAPI** with Pydantic models (`app/models.py`)
- **Firestore** via `firebase-admin` (`app/firebase_setup.py`)
- **Google Calendar API** for external calendar sync
- **Stripe** for payments
- **APScheduler** for recurring background tasks
- **Logfire** for observability

## Project Structure

```
app/
  main.py              # FastAPI app, scheduler setup
  models.py            # Pydantic models (TripData, GCalEvent, etc.)
  firebase_setup.py    # Firestore client init
  utils.py             # Settings, logger
  cal/
    tasks.py           # Calendar sync logic (sync_calendar_events, handle_validated_event, etc.)
    views.py           # Calendar API endpoints
    webhooks.py        # Google Calendar push notification handler
  pay/
    tasks.py           # Stripe payment logic (refunds, charges, transfers)
    views.py           # Payment API endpoints
  auth/
    tasks.py           # Auth logic
    views.py           # Auth endpoints
  auto/
    tasks.py           # auto_complete_and_notify — marks past trips complete, sends notifications
    cal_tasks.py       # auto_check_and_renew_channels — renews Google Calendar watch channels
    payout_task.py     # process_platform_payout — handles host payouts
    transaction_tasks.py # process_transactions — processes pending transactions
```

## Calendar Sync (app/cal/)

Google Calendar events sync bidirectionally with Firestore `trips` collection.

### Inbound: Google Calendar -> Firestore trips
1. Google sends push notification to `webhooks.py` when events change
2. `sync_calendar_events()` fetches changes via incremental sync (syncToken)
3. Each event is validated as `GCalEvent` or `CancelledGCalEvent`
4. `handle_validated_event()` creates/updates trip; `handle_cancelled_event()` deletes trips

### Outbound: Firestore trips -> Google Calendar
- `create_or_update_event_from_trip()` pushes internal bookings to Google Calendar
- `delete_event_from_trip()` removes cancelled bookings

### Duplicate prevention
- `create_new_trip()` uses `event.id` as the Firestore document ID (`db.collection('trips').document(event.id).set(...)`) so concurrent syncs write to the same document instead of creating duplicates
- `handle_validated_event()` also cleans up any legacy duplicates (with auto-generated IDs) by keeping the first match and deleting the rest
- `handle_cancelled_event()` deletes ALL trips matching the eventId

### Timezone handling
- Timed events: `datetime.fromisoformat()` preserves the offset from Google Calendar (e.g. `-07:00`). Firestore's Python client converts timezone-aware datetimes to UTC on write.
- All-day events: `Date` type — midnight is localized to the property timezone via `pytz.timezone.localize()` before storage.
- `tripDate` is set to `start_datetime.replace(hour=0, minute=0, second=0)` which preserves the timezone offset.

## Payments (app/pay/)

- Stripe Connect: hosts are connected accounts, platform takes fees
- Off-session payments for host-initiated bookings
- Refund handling (full and partial)
- Extra charges for disputes

## Scheduled Tasks (app/auto/)

Run via APScheduler on startup, then at intervals:
- `auto_complete_and_notify` — every 1h, marks past trips as complete, sends review notifications
- `process_transactions` — every 1h, processes pending financial transactions
- `process_platform_payout` — every 1h, handles host payouts
- `auto_check_and_renew_channels` — every 12h, renews Google Calendar watch channels before expiry

## Key Models (app/models.py)

- `TripData` — Firestore trip document fields (tripBeginDateTime, tripEndDateTime, tripDate, eventId, etc.)
- `GCalEvent` / `CancelledGCalEvent` — Google Calendar event validation
- `OffSessionPayment` — host-initiated payment request
- `Transaction` — financial transaction record

## Git

- Main branch: `main`
- Deployed directly from main
