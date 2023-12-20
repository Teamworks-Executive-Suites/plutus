import os

import unittest
from unittest.mock import patch

from main import app
from fastapi.testclient import TestClient
import stripe

from unittest.mock import MagicMock

client = TestClient(app)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

from settings import Settings

settings = Settings()


# need a fake firestore trip to test with
class FakeFirestore:
    def __init__(self):
        self.db = {
            "trips": {
                "fake_trip_ref": {
                    "Document ID": "",
                    "cancelTrip": False,
                    "complete": False,
                    "editedTripRef": "",
                    "guests": [],
                    "host": "",
                    "inquiryDescription": "",
                    "isBlocked": False,
                    "isExternal": False,
                    "isInquiry": False,
                    "isOffer": False,
                    "isRefunded": False,
                    "isTempEditTrip": False,
                    "propertyRef": "",
                    "rated": False,
                    "stripePaymentIntents": [],
                    "tripAddonTotal": 0,
                    "tripBaseTotal": 0,
                    "tripBeginDateTime": "",
                    "tripCost": 0,
                    "tripCreated": "",
                    "tripDate": "",
                    "tripEndDateTime": "",
                    "tripReason": "",
                    "upcoming": False,
                    "userRef": ""
                }
            },
            "users": {
                "fake_user_ref": {
                    "Document ID": "",
                    "bio": "",
                    "company": "",
                    "created_time": "",
                    "display_name": "",
                    "email": "",
                    "isAdmin": False,
                    "isHost": False,
                    "numberProperties": 0,
                    "phone_number": "",
                    "photo_url": "",
                    "termsandconditionsaccepted": False,
                    "uid": "",
                    "userCity": "",
                    "fcm_tokens": []
                }
            }
        }



def get_or_create_customer(email: str, name: str):
    customers = stripe.Customer.list(email=email).data
    if customers:
        # Customer already exists, return the existing customer
        return customers[0]
    else:
        # Customer does not exist, create a new one
        return stripe.Customer.create(name=name, email=email)




class StripeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.fake_firestore = FakeFirestore()

        self.customer = get_or_create_customer('test_ricky_bobby@example.com', 'Ricky Bobby')

        settings.testing = True
        self.headers = {
            "Authorization": f'Bearer {settings.test_token}'
        }

    @patch('tasks.get_document_from_ref')
    def test_simple_refund(self, get_document_from_ref_mock):
        # Create a mock Firestore DocumentSnapshot
        mock_document_snapshot = MagicMock()
        mock_document_snapshot.exists = True
        mock_document_snapshot.to_dict.return_value = self.fake_firestore.db["trips"]["fake_trip_ref"]

        # Define what the mock should do when called
        get_document_from_ref_mock.return_value = mock_document_snapshot

        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.fake_firestore.db["trips"]["fake_trip_ref"]["stripePaymentIntents"].append(pi.id)


        data = {
            "trip_ref": "trips/fake_trip_ref",
            "amount": 1099
        }
        r = self.client.post("/refund", headers=self.headers, json=data)
        debug(r.json())
        # Check the result
        self.assertEqual(r.status_code, 200)

        # Verify the mock was called with the correct arguments
        get_document_from_ref_mock.assert_called_once_with("trips/fake_trip_ref")