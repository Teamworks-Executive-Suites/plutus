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

### Refund Endpoint

This endpoint handles refunding a specific amount for trips using the Stripe API and Firebase.

Endpoint: `/refund`

#### Request

```bash
POST /refund_deposit
Content-Type: application/json

{
"trip_ref": "your_trip_reference",
"amount": "your_amount"
}
```

#### Response

- `200 OK`: Refund successful
- `4xx` Status Codes: Error messages for different scenarios

### Extra Charge Endpoint

This endpoint handles charging the Stripe Customer's off-session card with the amount set in the Dispute.

Endpoint: `/extra_charge`

#### Request

```bash 
POST /extra_charge
Content-Type: application/json

{
"trip_ref": "your_trip_reference",
"dispute_ref": "the_dispute_reference",
}
```

#### Response

- `200 OK`: Charge successful
- `4xx` Status Codes: Error messages for different scenarios

### Cancel Refund Endpoint

This endpoint handles the cancellation of a trip, refunding to customer the correct amount due to the property's Cancelation Policy.
This enpoint also has a paramerter to provide a full refund to the customer for when the Host cancels the booking.

Endpoint: `/cancel_refund`

#### Request

```bash
POST /cancel_refund
Content-Type: application/json

{
    "trip_ref": "your_trip_reference",
    "full_refund": "boolean"
}
```

#### Response

- `200 OK`: Refund successful
- `4xx` Status Codes: Error messages for different scenarios




### Get Property Calendar Endpoint

This endpoint generates an iCalendar
} (.ics) file containing property trip events.

Endpoint: `/get_property_cal`

#### Request

```bash
POST /get_property_cal
Content-Type: application/json

{
"property_ref": "your_property_reference"
}
```

#### Response

- `200 OK`: Returns the file path of the generated .ics file

### Calendar to Property Endpoint

This endpoint creates trip documents based on iCalendar events.

Endpoint: `/cal_to_property`

#### Request

```bash
POST /cal_to_property
Content-Type: application/json

{
"property_ref": "your_property_reference",
"ics_link": "your_ics_link"
}
```

#### Response

- `200 OK`: Trip documents created successfully

## Configuration

Before using the endpoints, make sure to configure the necessary environment variables for Firebase and Stripe in a `.env` file in the root directory of the repository.

- `GOOGLE_APPLICATION_CREDENTIALS`: Firebase configuration JSON string
- `STRIPE_SECRET_KEY`: Your Stripe API key

## Testing

before running stripe tests make sure to have the following environment variables set:

`export testing=True`

to test the stripe tests use:

`pytest -k {testname} -s'


## Logfire:

[Logfire](https://dash.logfire.dev/PrenSJ2/plutus)

run `logfire whoami to get the url with token`