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
                    "id": "fake_trip_ref",
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
                    "id": "fake_user_ref",
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
            },
            "properties": {
                "fake_property_ref": {
                    "cancellationPolicy": "",
                    "checkInInstructions": "",
                    "cleaningFee": 0,
                    "externalCalendar": "",
                    "hostRules": "",
                    "id": "fake_property_ref",
                    "isDraft": False,
                    "isLive": True,
                    "lastUpdated": "",
                    "mainImage": [],
                    "maxGuests": 0,
                    "minHours": 4,
                    "notes": "",
                    "parkingInstructions": "",
                    "price": [0, 0, 0, 0, 0, 0],
                    "propertyAddress": "",
                    "propertyArea": "",
                    "propertyDescription": "",
                    "propertyName": "Test Property",
                    "ratingSummary": 5,
                    "sqft": 450,
                    "taxRate": 0,
                    "userRef": "users/fake_user_ref",
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


class MockDB:
    def __init__(self, data):
        self.data = data
        debug(self.data)

    def collection(self, collection_name):
        debug(collection_name)
        if collection_name in self.data:
            return MockCollection(self.data[collection_name])
        else:
            raise ValueError(f"Collection {collection_name} does not exist in the mock data.")

class MockCollection:
    def __init__(self, data):
        self.data = data

    def document(self, document_name):
        if document_name in self.data:
            return MockDocument(self.data[document_name])
        else:
            raise ValueError(f"Document {document_name} does not exist in the mock data.")

class MockDocument:
    def __init__(self, data):
        self.data = data

    def get(self):
        debug(self.data)
        mock_snapshot = Mock()
        mock_snapshot.exists = bool(self.data)
        mock_snapshot.get = lambda key: self.data.get(key)
        mock_snapshot.to_dict = lambda: self.data
        return mock_snapshot

class StripeRefund(TestCase):
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

        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed successfully.'
        assert r.json()['total_refunded'] == 1099
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id

        self.assertEqual(r.status_code, 200)


    @patch('google.cloud.firestore_v1.collection.CollectionReference.document')
    def test_complex_one(self, document_mock):
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

        pi2 = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.fake_firestore.db["trips"]["fake_trip_ref"]["stripePaymentIntents"].append(pi2.id)

        data = {
            "trip_ref": "trips/fake_trip_ref",
            "amount": 1299
        }
        r = self.client.post("/refund", headers=self.headers, json=data)
        # Check the result

        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed successfully.'
        assert r.json()['total_refunded'] == 1299
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 200
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id

        self.assertEqual(r.status_code, 200)


class StripeCancelRefund(TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.fake_firestore = FakeFirestore()

        self.customer = get_or_create_customer('test_ricky_bobby@example.com', 'Ricky Bobby')

        settings.testing = True
        self.headers = {
            "Authorization": f'Bearer {settings.test_token}'
        }

    @patch('app.pay.tasks.db', new_callable=lambda: MockDB(FakeFirestore().db))
    @patch.object(MockDB, 'collection', return_value=MockCollection(FakeFirestore().db["trips"]))
    def test_simple_cancel_refund_with_string_property_ref(self, db_mock, collection_mock):
        # Create a mock Firestore document
        mock_document = Mock()

        # Create a mock DocumentSnapshot for the trip document
        mock_snapshot_trip = Mock()
        mock_snapshot_trip.exists = True
        mock_snapshot_trip.get = lambda key: self.fake_firestore.db["trips"]["fake_trip_ref"].get(key)
        mock_snapshot_trip.to_dict = lambda: self.fake_firestore.db["trips"]["fake_trip_ref"]

        # Set the return value of the get method of the mock document
        mock_document.get.return_value = mock_snapshot_trip

        # Set the return value of the document method of the db object to the mock document
        db_mock.collection().document.return_value = mock_document

        # Add property_ref to the trip document as a string
        self.fake_firestore.db["trips"]["fake_trip_ref"]["propertyRef"] = "fake_property_ref"

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 404
        assert r.json()['message'] == 'Property document not found.'

        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.status_code, 200)