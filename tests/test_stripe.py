import os
from datetime import timedelta
from unittest import TestCase

import stripe
from fastapi.testclient import TestClient
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from app.firebase_setup import MOCK_DB, current_time
from app.main import app
from app.utils import settings

# Set settings.testing to True before importing app/firebase_setup.py
settings.testing = True


client = TestClient(app)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


# need a fake firestore trip to test with
class FakeFirestore:
    def __init__(self):
        self.db = {
            'trips': {
                'fake_trip_ref': {
                    'id': 'fake_trip_ref',
                    'propertyRef': '',
                    'userRef': '',
                    'tripCost': 0,
                    'guests': 0,
                    'tripCreated': '',
                    'host': '',
                    'cancelTrip': False,
                    'upcoming': False,
                    'complete': False,
                    'rated': False,
                    'tripBeginDateTime': None,
                    'tripEndDateTime': None,
                    'isInquiry': False,
                    'tripTax': '',
                    'tripAddonTotal': 0,
                    'tripBaseTotal': 0,
                    'isExternal': False,
                    'isRefunded': False,
                    'tripDate': '',
                    'inquiryDescription': '',
                    'isOffer': False,
                    'tripReason': '',
                    'isBlocked': False,
                    'editedTripRef': '',
                    'isTempEditTrip': False,
                    'disputeRef': '',
                    'stripePaymentIntents': [],
                    'eventId': '',
                    'eventSummary': '',
                    'appliedDiscountRef': '',
                    'appliedDiscountAmount': '',
                }
            },
            'users': {
                'fake_user_ref': {
                    'id': 'fake_user_ref',
                    'bio': '',
                    'company': '',
                    'created_time': '',
                    'display_name': '',
                    'email': '',
                    'isAdmin': False,
                    'isHost': False,
                    'numberProperties': 0,
                    'phone_numbers': '',
                    'photo_url': '',
                    'termsandconditionsaccepted': False,
                    'uid': '',
                    'userCity': '',
                    'fcm_tokens': [],
                }
            },
            'properties': {
                'fake_property_ref': {
                    'cancellationPolicy': '',
                    'checkInInstructions': '',
                    'cleaningFee': 0,
                    'externalCalendar': '',
                    'hostRules': '',
                    'id': 'fake_property_ref',
                    'isDraft': False,
                    'isLive': True,
                    'lastUpdated': '',
                    'mainImage': [],
                    'maxGuests': 0,
                    'minHours': 4,
                    'notes': '',
                    'parkingInstructions': '',
                    'price': [0, 0, 0, 0, 0, 0],
                    'propertyAddress': '',
                    'propertyArea': '',
                    'propertyDescription': '',
                    'propertyName': 'Test Property',
                    'ratingSummary': 5,
                    'sqft': 450,
                    'taxRate': 0,
                    'userRef': 'users/fake_user_ref',
                }
            },
            'disputes': {
                'fake_dispute_ref': {
                    'id': 'fake_dispute_ref',
                    'tripRef': 'trips/fake_trip_ref',
                    'disputeCategory': 'damage',
                    'disputeAmount': 1000,
                    'disputeDescription': 'test',
                    'disputeCreated': None,
                    'paymentIntent': '',
                }
            },
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
#             raise ValueError("Document %S does not exist in the mock data.", document_id)
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
#             raise ValueError("Collection %s does not exist in the mock data.", collection_id)
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
        self.headers = {'Authorization': f'Bearer {settings.test_token}'}

        # Create a MockFirestore instance
        self.mock_firestore = MOCK_DB

        # Set up your mock data
        self.mock_firestore.collection('trips').document('fake_trip_ref').set(
            self.fake_firestore.db['trips']['fake_trip_ref']
        )
        self.mock_firestore.collection('properties').document('fake_property_ref').set(
            self.fake_firestore.db['properties']['fake_property_ref']
        )
        # Add property_ref to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({'propertyRef': 'fake_property_ref'})

    def test_simple_refund(self):
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip

        trip = self.mock_firestore.collection('trips').document('fake_trip_ref').get()
        current_intents = trip.get('stripePaymentIntents')
        current_intents.append(pi.id)
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': current_intents}
        )

        data = {'trip_ref': 'trips/fake_trip_ref', 'amount': 1099, 'actor_ref': 'users/fake_user_ref'}
        r = self.client.post('/refund', headers=self.headers, json=data)
        # Check the result

        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed successfully.'
        assert r.json()['total_refunded'] == 1099
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id

        self.assertEqual(r.status_code, 200)

    def test_complex_one(self):
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        trip = self.mock_firestore.collection('trips').document('fake_trip_ref').get()
        current_intents = trip.get('stripePaymentIntents')
        current_intents.append(pi.id)
        current_intents.append(pi2.id)
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': current_intents}
        )

        data = {'trip_ref': 'trips/fake_trip_ref', 'amount': 1299, 'actor_ref': 'users/fake_user_ref'}
        r = self.client.post('/refund', headers=self.headers, json=data)
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
        self.headers = {'Authorization': f'Bearer {settings.test_token}'}

        # Create a MockFirestore instance
        self.mock_firestore = MOCK_DB

        # Set up your mock data
        self.mock_firestore.collection('trips').document('fake_trip_ref').set(
            self.fake_firestore.db['trips']['fake_trip_ref']
        )
        self.mock_firestore.collection('properties').document('fake_property_ref').set(
            self.fake_firestore.db['properties']['fake_property_ref']
        )
        # Add property_ref to the trip document
        property_ref_object = self.mock_firestore.collection('properties').document('fake_property_ref').get()
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({'propertyRef': property_ref_object})

    def test_simple_cancel_refund(self):
        """
        This test has 1 payment intent
        less than 24hrs
        full refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Very Flexible'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update({'stripePaymentIntents': [pi.id]})

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=1)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1099
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['cancellation_policy'] == 'Very Flexible'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_2(self):
        """
        This test has 2 payment intent
        less than 24hrs
        full refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Very Flexible'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=1)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1600
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 501
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Very Flexible'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_3(self):
        """
        This test has 2 payment intent
        greater than 24hrs
        no refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Very Flexible'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=2)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

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
        assert r.json()['cancellation_policy'] == 'Very Flexible'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_4(self):
        """
        This test has 2 payment intents
        Flexible
        less than 7 days
        no refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Flexible'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=8)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

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
        assert r.json()['cancellation_policy'] == 'Flexible'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_5(self):
        """
        This test has 2 payment intents
        Flexible
        between 24hrs and 7 days
        50% refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Flexible'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=5)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

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
        assert r.json()['cancellation_policy'] == 'Flexible'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_6(self):
        """
        This test has 2 payment intents
        Flexible
        less than 24hrs
        no refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Flexible'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(hours=5)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

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
        assert r.json()['cancellation_policy'] == 'Flexible'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_7(self):
        """
        This test has 2 payment intents
        Standard 30 Day
        more than 30 days before
        100% refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Standard 30 Day'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=31)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1600
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['reason'] == '30 or more days before booking - 100% refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 501
        assert r.json()['refund_details'][1]['reason'] == '30 or more days before booking - 100% refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Standard 30 Day'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_8(self):
        """
        This test has 2 payment intents
        Standard 30 Day
        between 7 and 30 days
        50% refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Standard 30 Day'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=8)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 799
        assert r.json()['refund_details'][0]['refunded_amount'] == 549
        assert r.json()['refund_details'][0]['reason'] == 'Between 7 and 30 days before booking - 50% refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 250
        assert r.json()['refund_details'][1]['reason'] == 'Between 7 and 30 days before booking - 50% refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Standard 30 Day'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_9(self):
        """
        This test has 2 payment intents
        Standard 30 Day
        less than 7 days
        no refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Standard 30 Day'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=2)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 0
        assert r.json()['refund_details'][0]['refunded_amount'] == 0
        assert r.json()['refund_details'][0]['reason'] == 'Less than 7 days before booking - no refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 0
        assert r.json()['refund_details'][1]['reason'] == 'Less than 7 days before booking - no refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Standard 30 Day'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_10(self):
        """
        This test has 2 payment intents
        Standard 90 Day
        more than 90 days before
        100% refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Standard 90 Day'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=92)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1600
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['reason'] == '90 or more days before booking - 100% refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 501
        assert r.json()['refund_details'][1]['reason'] == '90 or more days before booking - 100% refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Standard 90 Day'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_11(self):
        """
        This test has 2 payment intents
        Standard 90 Day
        between 30 and 90 days
        50% refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Standard 90 Day'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=40)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 799
        assert r.json()['refund_details'][0]['refunded_amount'] == 549
        assert r.json()['refund_details'][0]['reason'] == 'Between 30 and 90 days before booking - 50% refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 250
        assert r.json()['refund_details'][1]['reason'] == 'Between 30 and 90 days before booking - 50% refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Standard 90 Day'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_12(self):
        """
        This test has 2 payment intents
        Standard 90 Day
        less than 30 days
        no refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Standard 90 Day'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=20)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 0
        assert r.json()['refund_details'][0]['refunded_amount'] == 0
        assert r.json()['refund_details'][0]['reason'] == 'Less than 30 days before booking - no refund'
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 0
        assert r.json()['refund_details'][1]['reason'] == 'Less than 30 days before booking - no refund'
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Standard 90 Day'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_refund_13(self):
        """
        This test has 2 payment intents
        Unknown Cancellation Policy
        random number of days
        no refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Unknown Cancellation Policy'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=20)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )
        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': False,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 0
        assert r.json()['refund_details'][0]['refunded_amount'] == 0
        assert r.json()['refund_details'][0]['reason'] == (
            'Cancellation policy not recognized: Unknown Cancellation ' 'Policy - no refund - please contact support'
        )
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 0
        assert r.json()['refund_details'][1]['reason'] == (
            'Cancellation policy not recognized: Unknown Cancellation ' 'Policy - no refund - please contact support'
        )
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Unknown Cancellation Policy'

        self.assertEqual(r.status_code, 200)

    def test_simple_cancel_full_refund_13(self):
        """
        This test has 2 payment intents
        full refund = True
        Unknown Cancellation Policy
        random number of days
        full refund
        :return:
        """

        # Add Cancellation Policy to the property document
        self.mock_firestore.collection('properties').document('fake_property_ref').update(
            {'cancellationPolicy': 'Unknown Cancellation Policy'}
        )

        # Create a Stripe PaymentIntent
        pi = stripe.PaymentIntent.create(
            amount=1099,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        pi2 = stripe.PaymentIntent.create(
            amount=501,
            currency='usd',
            customer=self.customer.id,
            payment_method='pm_card_visa',
            off_session=True,
            confirm=True,
        )

        # Add payment to trip
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'stripePaymentIntents': [pi.id, pi2.id]}
        )

        # Create a datetime object
        trip_begin_datetime = current_time - timedelta(days=20)

        # Convert the datetime object to a DatetimeWithNanoseconds object
        trip_begin_datetime = DatetimeWithNanoseconds.fromtimestamp(trip_begin_datetime.timestamp())

        # Add tripBeginDateTime to the trip document
        self.mock_firestore.collection('trips').document('fake_trip_ref').update(
            {'tripBeginDateTime': trip_begin_datetime}
        )

        data = {
            'trip_ref': 'trips/fake_trip_ref',
            'full_refund': True,
            'actor_ref': 'users/fake_user_ref',
        }
        r = self.client.post('/cancel_refund', headers=self.headers, json=data)

        # Check the result
        assert r.json()['status'] == 200
        assert r.json()['message'] == 'Refund processed.'
        assert r.json()['total_refunded'] == 1600
        assert r.json()['refund_details'][0]['refunded_amount'] == 1099
        assert r.json()['refund_details'][0]['reason'] == ('Host cancelled Booking - Full Refund')
        assert r.json()['refund_details'][0]['payment_intent_id'] == pi.id
        assert r.json()['refund_details'][1]['refunded_amount'] == 501
        assert r.json()['refund_details'][1]['reason'] == ('Host cancelled Booking - Full Refund')
        assert r.json()['refund_details'][1]['payment_intent_id'] == pi2.id
        assert r.json()['cancellation_policy'] == 'Unknown Cancellation Policy'

        self.assertEqual(r.status_code, 200)


# class StripeExtraCharge(TestCase):
#     def setUp(self) -> None:
#         self.client = TestClient(app)
#         self.fake_firestore = FakeFirestore()
#
#         self.customer = get_or_create_customer('test_extra_charge@example.com', 'John Smith Extra Charge')
#
#         settings.testing = True
#         self.headers = {
#             "Authorization": f'Bearer {settings.test_token}'
#         }
#
#         # Create a MockFirestore instance
#         self.mock_firestore = MOCK_DB
#
#         # Set up your mock data
#         self.mock_firestore.collection('trips').document('fake_trip_ref').set(
#             self.fake_firestore.db["trips"]["fake_trip_ref"]
#         )
#         self.mock_firestore.collection('properties').document('fake_property_ref').set(
#             self.fake_firestore.db["properties"]["fake_property_ref"]
#         )
#         # Add property_ref to the trip document
#         self.mock_firestore.collection('trips').document('fake_trip_ref').update({
#             "propertyRef": "fake_property_ref"
#         })
#
#         # Add a dispute to the mock firestore
#         self.mock_firestore.collection('disputes').document('fake_dispute_ref').set(
#             self.fake_firestore.db["disputes"]["fake_dispute_ref"]
#         )
#
#     def test_simple_extra_charge(self):
#         '''
#         This test has 1 payment intent
#         :return:
#         '''
#
#         # need to check and figure out how this works
#
#         # think we should check the pm and customer is the same as the previous pi
#
#         # check it went through
#
#
#         # Simulate making a booking with payment intent
#
#         # Create a Stripe PaymentIntent - this simulate a booking
#         pi = stripe.PaymentIntent.create(
#             amount=1099,
#             currency='usd',
#             customer=self.customer.id,
#             payment_method="pm_card_visa",
#             off_session=True,
#             confirm=True,
#         )
#
#
#
#         # Add payment to trip
#         self.mock_firestore.collection('trips').document('fake_trip_ref').update({
#             "stripePaymentIntents": [pi.id]
#         })
#
#
#         # Then we want to create the dipute
#
#         # Create a Dispute - made in setup
#
#
#
#         # Then we need to check that the stripe dispute is auto charged to the same stripe customer and payment method as the original payment intent
#
#
#
#         data = {
#             "trip_ref": "trips/fake_trip_ref",
#             "dispute_ref": "disputes/fake_dispute_ref"
#         }
#         r = self.client.post("/extra_charge", headers=self.headers, json=data)
#         debug(r.json())
#
#
#         # Check the result
#         assert r.json()['status'] == 200
#         assert r.json()['message'] == 'Extra charge processed successfully.'
#         assert r.json()['details']['payment_intent']
#
#         self.assertEqual(r.status_code, 200)
