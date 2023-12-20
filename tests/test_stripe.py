import os

import unittest
from unittest.mock import patch

from bearer_token import generate_bearer_token
from main import app
from fastapi.testclient import TestClient
import stripe

from unittest.mock import MagicMock
from tasks import get_document_from_ref

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


class StripeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.fake_firestore = FakeFirestore()

        self.customer = stripe.Customer.create(
            name='Test Customer',
            email='test_customer@example.com',
        )

        self.pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )
        settings.testing = True
        self.headers = {
            "Authorization": f'Bearer {settings.test_token}'
        }

    @patch('firebase_admin.firestore.client')
    def test_simple_refund(self, firestore_client_mock):
        # Define what the mock should do when called

        firestore_client_mock.collection().document().get.return_value = self.fake_firestore.db["trips"][
            "fake_trip_ref"]

        # Add payment to trip
        self.fake_firestore.db["trips"]["fake_trip_ref"]["stripePaymentIntents"].append(self.pi.id)
        data = {
            "trip_ref": "trips/fake_trip_ref",
            "amount": 1099
        }
        r = self.client.post("/refund", headers=self.headers, json=data)
        debug(r.content)
        # Check the result
        self.assertEqual(r.status_code, 200)

        # Verify the mock was called with the correct arguments
        firestore_client_mock.collection.assert_called_with("trips")
        firestore_client_mock.collection().document.assert_called_with("fake_trip_ref")
        firestore_client_mock.collection().document().get.assert_called_once()
