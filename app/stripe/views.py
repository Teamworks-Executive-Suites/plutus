from fastapi import APIRouter, Depends
from app.auth.views import get_token

from app.models import Trip, Refund
from app.stripe.tasks import process_extra_charge, handle_refund, process_cancel_refund
from devtools import debug

stripe_router = APIRouter()


@stripe_router.post("/extra_charge")
def extra_charge(data: Trip, token: str = Depends(get_token)):
    return process_extra_charge(data.trip_ref)


@stripe_router.post("/refund")
def refund(data: Refund, token: str = Depends(get_token)):
    debug(data)
    print('reeeee')
    return handle_refund(data.trip_ref, data.amount)


@stripe_router.post("/cancel_refund")
def cancel_refund(data: Trip, token: str = Depends(get_token)):
    return process_cancel_refund(data.trip_ref)

