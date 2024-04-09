# Plutus - Teamworks API

Plutus was a Greek deity, considered the Greek god of wealth, This repository contains a FastAPI application that interacts with Firebase and external services to provide functionality related to property trips and refunds.

Plutus manages complex refunds, extra charges through stripe and ical generation and syncing

## Installation

1. Clone this repository to your local machine.
2. Create a virtual environment (optional but recommended):
```bash
python -m venv env
```
3. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Usage

To Start the FastAPI application, run the following command:
```bash
uvicorn app.main:app --reload
```
## Endpoints

### Auth Endpoints

- `GET /token`: Retrieves the token for a user.

### Calendar Endpoints

- `POST /set_google_calendar_id`: Sets the Google Calendar ID for a property.
- `POST /event_from_trip`: Creates or updates an event from a trip.
- `DELETE /event_from_trip`: Deletes an event from a trip.

### Stripe Endpoints

- `POST /extra_charge`: Processes an extra charge for a trip with a dispute.
- `POST /refund`: Processes a refund for a trip.
- `POST /cancel_refund`: Cancels a refund for a trip.

### Calendar Webhook Endpoints

- `POST /cal_webhook`: Receives a webhook with a calendar ID.
- `POST /delete_webhook_channel`: Deletes a webhook channel.

## Configuration

Before using the endpoints, make sure to configure the necessary environment variables for Firebase and Stripe in a `.env` file in the root directory of the repository.

- `GOOGLE_APPLICATION_CREDENTIALS`: Firebase configuration JSON string
- `STRIPE_SECRET_KEY`: Your Stripe API key

look in settings.py for more

if you want to adjust the buffer time before and after calendar events, you can adjust the:

- `BUFFER_TIME`: Buffer time in minutes


## How to connect a Google Calendar to a Teamworks office and Peerspace office

Look at the instructions [here](https://github.com/Teamworks-Executive-Suites/teamworks/issues/75#issuecomment-2041655913)

## Testing

before running stripe tests make sure to have the following environment variables set:

`export testing=True`

to test the stripe tests use:

`pytest -k {testname} -s'


## Logfire:

[Logfire](https://dash.logfire.dev/PrenSJ2/plutus)

run `logfire whoami to get the url with token`