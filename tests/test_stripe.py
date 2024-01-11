import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import stripe
import unittest
from unittest import TestCase

from fastapi.testclient import TestClient
from mockfirestore import MockFirestore

from app.main import app
from app.firebase_setup import db, MOCK_DB, current_time

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
                    "tripBeginDateTime": None,
                    "tripCost": 0,
                    "tripCreated": "",
                    "tripDate": "",
                    "tripEndDateTime": None,
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

#
# # Ensure that the MockDB and its related classes (MockCollection, MockDocument) are working correctly
#
# # Look to we mock stripe on TC
# class FakeDocument:
#     def __init__(self, data):
#         self.data = data
#
#     def get(self):
#         debug('FakeDocument get')
#         debug(self.data)
#         return self.data
#
#
# class FakeCollection:
#     def __init__(self, data):
#         self.data = data
#
#     def document(self, document_id):
#         debug('FakeCollection document')
#         debug(self.data)
#         if document_id in self.data:
#             return FakeDocument(self.data[document_id])
#         else:
#             raise ValueError(f"Document {document_id} does not exist in the mock data.")
#
#
# class FakeClient:
#     def __init__(self, data):
#         self.data = data
#         debug('FakeClient init')
#
#     def collection(self, collection_id):
#         debug('FakeClient collection')
#         if collection_id in self.data:
#             return FakeCollection(self.data[collection_id])
#         else:
#             raise ValueError(f"Collection {collection_id} does not exist in the mock data.")
#

def get_or_create_customer(email: str, name: str):
    customers = stripe.Customer.list(email=email).data
    if customers:
        # Customer already exists, return the existing customer
        return customers[0]
    else:
        # Customer does not exist, create a new one
        return stripe.Customer.create(name=name, email=email)


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

        # Create a MockFirestore instance
        self.mock_firestore = MOCK_DB

        # Set up your mock data
        self.mock_firestore.collection('trips').document('fake_trip_ref').set(
            self.fake_firestore.db["trips"]["fake_trip_ref"]
        )
        self.mock_firestore.collection('properties').document('fake_property_ref').set(
            self.fake_firestore.db["properties"]["fake_property_ref"]
        )
        # Add property_ref to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "propertyRef": "fake_property_ref"
        })

    def test_simple_cancel_refund(self):
        '''
        This test has 1 payment intent
        less than 24hrs
        full refund
        :return:
        '''

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update({
            "cancellationPolicy": "Very Flexible"
        })

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "stripePaymentIntents": [pi.id]
        })

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=1)

        # Convert the datetime object to a timestamp
        trip_begin_timestamp = trip_begin_datetime.timestamp()

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "tripBeginDateTime": trip_begin_timestamp
        })

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)
        debug(r.json())

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1099
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['cancellation_policy'] == "Very Flexible"

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_2(self):
        '''
        This test has 2 payment intent
        less than 24hrs
        full refund
        :return:
        '''

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update({
            "cancellationPolicy": "Very Flexible"
        })

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "stripePaymentIntents": [pi.id, pi2.id]
        })

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=1)

        # Convert the datetime object to a timestamp
        trip_begin_timestamp = trip_begin_datetime.timestamp()

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "tripBeginDateTime": trip_begin_timestamp
        })

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)
        debug(r.json())

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1600
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 501
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == "Very Flexible"

        self.assertEqual(r.status_code, 200)


    def test_simple_cancel_refund_3(self):
        '''
        This test has 2 payment intent
        greater than 24hrs
        no refund
        :return:
        '''

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update({
            "cancellationPolicy": "Very Flexible"
        })

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "stripePaymentIntents": [pi.id, pi2.id]
        })

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=2)

        # Convert the datetime object to a timestamp
        trip_begin_timestamp = trip_begin_datetime.timestamp()

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "tripBeginDateTime": trip_begin_timestamp
        })

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)
        debug(r.json())

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 0
        assert r.json()['refund_details'][0]['refunded_amount'] == 0
        assert r.json()['refund_details'][0]['reason'] == 'Less than 24 hours before trip - no refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 0
        assert r.json()['refund_details'][1]['reason'] == 'Less than 24 hours before trip - no refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == "Very Flexible"

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_4(self):
        '''
        This test has 2 payment intents
        Flexible
        less than 7 days
        no refund
        :return:
        '''

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update({
            "cancellationPolicy": "Flexible"
        })

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "stripePaymentIntents": [pi.id, pi2.id]
        })

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=8)

        # Convert the datetime object to a timestamp
        trip_begin_timestamp = trip_begin_datetime.timestamp()

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "tripBeginDateTime": trip_begin_timestamp
        })

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)
        debug(r.json())

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1600
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['reason'] == '7 or more days before booking - 100% refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 501
        assert r.json()['refund_details'][1]['reason'] == '7 or more days before booking - 100% refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == "Flexible"

        self.assertEqual(r.status_code, 200)


    def test_simple_cancel_refund_5(self):
        '''
        This test has 2 payment intents
        Flexible
        between 24hrs and 7 days
        50% refund
        :return:
        '''

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update({
            "cancellationPolicy": "Flexible"
        })

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "stripePaymentIntents": [pi.id, pi2.id]
        })

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=5)

        # Convert the datetime object to a timestamp
        trip_begin_timestamp = trip_begin_datetime.timestamp()

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "tripBeginDateTime": trip_begin_timestamp
        })

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)
        debug(r.json())

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 799
        assert r.json()['refund_details'][0]['refunded_amount'] == 549
        assert r.json()['refund_details'][0]['reason'] == 'Between 24 hours and 7 days before booking - 50% refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 250
        assert r.json()['refund_details'][1]['reason'] == 'Between 24 hours and 7 days before booking - 50% refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == "Flexible"

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_6(self):
        '''
        This test has 2 payment intents
        Flexible
        less than 24hrs
        no refund
        :return:
        '''

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update({
            "cancellationPolicy": "Flexible"
        })

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method="pm_card_visa",
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "stripePaymentIntents": [pi.id, pi2.id]
        })

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(hours=5)

        # Convert the datetime object to a timestamp
        trip_begin_timestamp = trip_begin_datetime.timestamp()

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({
            "tripBeginDateTime": trip_begin_timestamp
        })

        data = {
            "trip_ref": "trips/fake_trip_ref",
        }
        r = self.client.post("/cancel_refund", headers=self.headers, json=data)
        debug(r.json())

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 0
        assert r.json()['refund_details'][0]['refunded_amount'] == 0
        assert r.json()['refund_details'][0]['reason'] == 'Less than 24 hours before booking - no refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 0
        assert r.json()['refund_details'][1]['reason'] == 'Less than 24 hours before booking - no refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == "Flexible"

        self.assertEqual(r.status_code, 200)