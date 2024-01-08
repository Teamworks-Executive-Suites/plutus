import os
from unittest.mock import Mock, patch

import stripe
import unittest
from unittest import TestCase

from fastapi.testclient import TestClient


from app.main import app
from app.firebase_setup import db

client = TestClient(app)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

from app.settings import Settings

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


class StripeTestCase(TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.fake_firestore = FakeFirestore()

        self.customer = get_or_create_customer('test_ricky_bobby@example.com', 'Ricky Bobby')

        settings.testing = True
        self.headers = {
            "Authorization": f'Bearer {settings.test_token}'
        }


    @patch('google.cloud.firestore_v1.collection.CollectionReference.document')
    def test_simple_refund(self, document_mock):
        # Create a mock Firestore document
        mock_document = Mock()

        # Create a mock DocumentSnapshot
        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.get = lambda key: self.fake_firestore.db["trips"]["fake_trip_ref"].get(
            key)  # Use a lambda function here

        mock_document.get.return_value = mock_snapshot
        document_mock.return_value = mock_document

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
        # Check the result
        self.assertEqual(r.status_code, 200)


    # @patch('app.pay.tasks.get_document_from_ref')
    # def test_complex_refund_one(self, get_document_from_ref_mock):
    #     # This test will replicate when a guest has made a booking, then made an adjustment to the booking to get an
    #     # extra addon. Therefore there will be two payment intents on the trip, one for the base trip cost,
    #     # and one for the addon cost. Then the guest will cancel the trip, and the refund will be for the base trip
    #     # cost.
    #
    #     # Create a mock Firestore DocumentSnapshot
    #     mock_document_snapshot = MagicMock()
    #     mock_document_snapshot.exists = True
    #     mock_document_snapshot.to_dict.return_value = self.fake_firestore.db["trips"]["fake_trip_ref"]
    #
    #     # Define what the mock should do when called
    #     get_document_from_ref_mock.return_value = mock_document_snapshot
    #
    #     # Create the first payment intent
    #     pi = stripe.PaymentIntent.create(
    #         amount=1099,
    #         currency='usd',
    #         customer=self.customer.id,
    #         payment_method="pm_card_visa",
    #         off_session=True,
    #         confirm=True,
    #     )
    #
    #     # Add payment to trip
    #     self.fake_firestore.db["trips"]["fake_trip_ref"]["stripePaymentIntents"].append(pi.id)
    #
    #     # Create the second payment intent
    #     pi2 = stripe.PaymentIntent.create(
    #         amount=999,
    #         currency='usd',
    #         customer=self.customer.id,
    #         payment_method="pm_card_visa",
    #         off_session=True,
    #         confirm=True,
    #     )
    #
    #     # Add payment to trip
    #     self.fake_firestore.db["trips"]["fake_trip_ref"]["stripePaymentIntents"].append(pi2.id)
    #
    #     # setup refund request data
    #     data = {
    #         "trip_ref": "trips/fake_trip_ref",
    #         "amount": 1099
    #     }
    #
    #     r = self.client.post("/refund", headers=self.headers, json=data)
    #     debug(r.json())
    #     # Check the result
    #     self.assertEqual(r.status_code, 200)
    #
    #     # Verify the mock was called with the correct arguments
    #     get_document_from_ref_mock.assert_called_once_with("trips/fake_trip_ref")
