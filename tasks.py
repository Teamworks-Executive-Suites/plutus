import requests
import pyrebase
import devtools
from ics import Calendar, Event
from datetime import datetime, timedelta
from urllib.parse import quote

# Stripe Functions


firebaseConfig = {
    # "apiKey": "AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY", it is missing an api key or it should be configured as a service worker
    "type": "service_account",
    "project_id": "teamworks-3b262",
    "private_key_id": "ede3d59c3a057c8c136e1d941390e54aca895bdb",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQC2NDzPYEubK50b\nPbhZFrUXAhDlGE3eEAvQRoQBBNszGGfQtRenbozYJ1QvCIg5oo5v43lORrnGvfQM\nRwgkVNycyW5HJtZoYgpbBFl1s4LO7pGC4LEkgeO1gedRI/BcK+zekfiMeBOXxq1i\nwWQk+MUXZEHjDhXxTSpE/yLBrszsEpV2ZpP7Uesx4KJ6BiRlIex5C4k2dNXZ3JZF\nV7iGqVmcpewMhuqnopoz8F1Bmatk8wYEJLJlQ0K+MMs0J5lWqStET+xX3qLryvuh\n8j8XNfOq2AR+DzTkfvDJ/tgiWvpNIeG+UIR3uOpG7Iw8bP1BB3Faj094Gp48VvIU\nWtc3kC9NAgMBAAECggEAANqI5poHckEEaCsdzz4+pHUA+I9oo/yN9Z1mKaDcC9n8\n+IeBebcYOu+gorGTsJ0JzxpKrsENk0UMdoQQFKcYiBwe45kmu+mQeo5jaRxpcm5z\nNfpqa6bRI8Ac6GHDX62UAa0ltAP6NLj8hhMsx/1c/Qfq+BudIwEiMtCoMsfOukdp\nxewTKM9Nz7CAe3S+Aqg6EqR8H5S7ZCEvJ1+Y7eX+c7q00WxV3tDMCfpAE4AqcZDd\nX/vkW9IsywSX2T8YOV2JpDrqGPxtGl3VMGrjLvOXsGszxWw2t9W/BIEEi5uyzQ0o\nkDuwYZJNNu71Jo4FCV5oLBcNoVlN3Z4iYKarwusvkQKBgQDyx/Rt5NOUq2CdezWv\nHTxBwPqO0pTRmFtf6RsjPHpCAmRiPDOoZLcpn0vKogx3WOutkba6wiL+kjr04n2W\nsB9XSkioA35tLAQ9MXLWpt+mMlS6XAV0VNuB0JAhCorDLu79VTThAE7OQxGuuFWY\n9gop9rHF7lnWMeqSvXJPFbSPnQKBgQDAH+tugtOyCK17YUI1VV9o4QnLb/W3lXD3\n3XcmspcvLZIpyLGPbFeSc6K8RI41ZXC86e6en+NZkCVODYLutz6+c4qEJurJaR7y\n7FPizKb5i5zaJA04SYz2SlFI5IB122iH9KySiGU+YKxlx9DdUeoxlx6CqHKbKtBs\n27l07FWHcQKBgQDY+M5/8AMPWOHtnBFsQMp7UUYboiMR9gGjg6aXJRN2LsEb8gWQ\ntwHiltSbcZuGhdeKtTEDU0EHFhTOiiQHKbu4vVCVpxmz46SeM7UYFObHly+VpWvS\nfYv3Rjeo78z3hthbW2z4sNe9Cr+g0GjfXPPUcP6Lj+qFvPKQ1fJ0r0dBGQKBgQCx\nvVX7WQEsFacZG7M60A6CYp7DHIMAIjrutG5E2LfRJ6GvEkJiY2Lo1B3berjtYTlZ\nLDpbeaPE+fvpJ8rXuaNMYmvlMnPHfX7qUgSRL6/R8X1cujmYt0K3n61veCX34tHj\n5VG6BoFTofAcAS2TcvLsidfqHJhaQNOtweDi8Ll3oQKBgQCzu2TJ/aIZBUUTz4wY\nREXjLRSz4i0ntnv8Vo4YOjh5LTij4ZNe3RzzqhKnKnf1z7ZEguDymILTTWM2hRX8\ncZqNjhaHP0cyKxxagBr80gHr4e3hxy9rmoApJzzlWNa47uzvYkjI3UrznfRYlyKm\nAmfDQ8caDr9vlQNBNaFwdY7nBw==\n-----END PRIVATE KEY-----\n",
    "client_email": "firebase-adminsdk-sbxn6@teamworks-3b262.iam.gserviceaccount.com",
    "client_id": "118063635413441766689",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-sbxn6%40teamworks-3b262.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
}

firebase = pyrebase.initialize_app(firebaseConfig)
db = firebase.storage()


def get_dispute_from_firebase(ref):
    dis = db.child("disputes").child(ref).get()
    return dis.val()


def create_cal_for_property(propertyRef):
    trips = db.child("trips").child(propertyRef).get()

    # create a calendar from the trips
    cal = Calendar()
    for trip in trips:
        # propertyRef = trip.propertyRef #
        property = db.child("properties").get()
        debug(property)
        cal_event = Event()
        cal_event.name = trip.name
        cal_event.begin = trip.tripBeginDateTime
        cal_event.end = trip.tripEndDateTime
        cal_event.url = trip.url
        cal.events.add(cal_event)

        cal_link = "test"

    return cal_link


def nica_demo(ref):
    trip = db.child("trips").child(ref)
    trip.update({"guests": "7"})
