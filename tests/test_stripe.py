import os

from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app
import stripe

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





class StripeTestCase:
    def setUp(self) -> None:
        settings.testing = True
        self.fake_firestore = FakeFirestore()

        firestore_client_mock = MagicMock()

        firestore_client_mock.collection().document().get.return_value = self.fake_firestore.db["trips"]["fake_trip_ref"]

        self.customer = stripe.Customer.create(
            name='Test Customer',
            email='test_customer@example.com',
        )
        self.pm = stripe.PaymentMethod.create(
            type="card",
            card={
                "number": '4242424242424242',
                "exp_month": 12,
                "exp_year": 2021,
                "cvc": '123',
            },
        )

        self.pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method=self.pm.id,
            # return_url='https://example.com/order/123/complete',
            off_session=True,
            confirm=True,
        )


    @patch('firebase_admin.firestore.client')
    def test_simple_refund(self, firestore_client_mock):
        # Create a mock Firestore client
        firestore_client_mock = MagicMock()

        # Define what the mock should do when called
        firestore_client_mock.collection().document().get.return_value = self.fake_firestore.db["trips"]["fake_trip_ref"]

        # Add payment to trip
        self.fake_firestore.db["trips"]["fake_trip_ref"]["stripePaymentIntents"].append(self.pi.id)

        r = client.post("/refund", json={"trip_ref": "fake_trip_ref"})

        # Check the result
        assert r.status_code == 200

        # Verify the mock was called with the correct arguments
        firestore_client_mock.collection.assert_called_with("trips")
        firestore_client_mock.collection().document.assert_called_with("fake_trip_ref")
        firestore_client_mock.collection().document().get.assert_called_once()