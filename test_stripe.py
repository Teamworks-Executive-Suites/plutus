import os
import pytest
from unittest import mock
from fastapi.testclient import TestClient
import stripe
from devtools import debug
from dotenv import load_dotenv

# Setup test environment
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_4eC39HqLyjWDarjtT1zdp7dc'

# Mocks setup for external services
stripe_mock = mock.Mock()

class TestAPIEndpoints:
    @pytest.fixture
    def client(self):
        # Setup FastAPI app and return test client
        app = ...  # Suppose this is the FastAPI app
        client = TestClient(app)
        return client

    def test_get_property_cal_success(self, client):
        response = client.get('/get_property_cal')
        assert response.status_code == 200
        assert 'cal_link' in response.json()

    def test_get_property_cal_invalid_property(self, client):
        response = client.get('/get_property_cal?property_ref=invalid')
        assert response.status_code != 200

    def test_cal_to_property_success(self, client):
        json_payload = {'property_ref': 'some_property', 'cal_link': 'http://example.com/cal'}
        response = client.post('/cal_to_property', json=json_payload)
        assert response.status_code == 200
        assert response.json() == {'message': 'Calendar event created successfully'}

    def test_cal_to_property_fail(self, client):
        json_payload = {'property_ref': 'some_property', 'cal_link': 'malformed_link'}
        response = client.post('/cal_to_property', json=json_payload)
        assert response.status_code != 200



    def test_cal_to_property(self):
        # TODO: Implement test cases for '/cal_to_property'
        pass

import os

import stripe
from devtools import debug
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')



# charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)
#
# debug(charge)

# charge = stripe.Charge.retrieve(
#   "ch_3Nk791DzTJHYWfEw0cULikcQ",
# )

# stripe.Refund.create(
#     charge=charge.id,
#     amount=1000,
# )

# stripe.PaymentMethod.list(
#   customer='cus_OK8AP9RpPEMrsM',
#   type="card",
# )

#
# try:
#     stripe.PaymentIntent.create(
#         amount=1099,
#         currency='usd',
#         # In the latest version of the API, specifying the `automatic_payment_methods` parameter is optional because Stripe enables its functionality by default.
#         automatic_payment_methods={"enabled": True},
#         customer='cus_OK8AP9RpPEMrsM', # need to get from payment intent
#         payment_method='pm_1NotP1DzTJHYWfEwXlBaphWv', # need to get from payment intent
#         # return_url='https://example.com/order/123/complete',
#         off_session=True,
#         confirm=True,
#     )
# except stripe.error.CardError as e:
#     err = e.error
#     # Error code will be authentication_required if authentication is needed
#     print("Code is: %s" % err.code)
#     payment_intent_id = err.payment_intent['id']
#     payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
#

payment_intent = stripe.PaymentIntent.retrieve("pi_3NxHl8DzTJHYWfEw1auGrNXH")
debug(payment_intent)