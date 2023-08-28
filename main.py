from fastapi import FastAPI
from models import *
from tasks import *
app = FastAPI()

# Nica was here

@app.get('/')
def hello():
    return {"hello world": "this worked!"}

@app.post('/edit')
def test_post(name: Name):
    return{ "message": f'hello {name} this test worked'}

@app.post('/refund_deposit')
def refund(ref: Dispute):
   # get dispute document from firebase where ref == ref
    # get user document from firebase where user == user
   get_dispute_from_firebase(ref)



    return {"message": f'hello {ref} this test worked'}


@app.get('/get_property_cal')
def get_property_cal(propertyRef: str):
    cal_link = create_cal_for_property(propertyRef)
    # add all cal stuff
    return {
        "propertyRef": propertyRef,
        "cal_link": cal_link
    }