import os

from fastapi.testclient import TestClient

from main import app
import stripe

client = TestClient(app)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')







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


def test_simple_refund():
    # create a payment intent for fake trip
    # pass fake trip to refund endpoint