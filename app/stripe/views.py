from fastapi import APIRouter

from app.models import Trip, Refund

stripe_router = APIRouter()


@app.post("/extra_charge")
def extra_charge(data: Trip, token: str = Depends(get_token)):
    return process_extra_charge(data.trip_ref)


@app.post("/refund")
def refund(data: Refund, token: str = Depends(get_token)):
    debug(data)
    print('reeeee')
    return handle_refund(data.trip_ref, data.amount)


@app.post("/cancel_refund")
def cancel_refund(data: Trip, token: str = Depends(get_token)):
    return process_cancel_refund(data.trip_ref)

