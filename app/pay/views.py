from fastapi import APIRouter, Depends

from app.auth.views import get_token
from app.models import CancelRefund, ExtraCharge, Refund
from app.pay._utils import app_logger
from app.pay.tasks import handle_refund, process_cancel_refund, process_extra_charge

stripe_router = APIRouter()


@stripe_router.post('/extra_charge')
def extra_charge(data: ExtraCharge, token: str = Depends(get_token)):
    app_logger.info(f'Extra charge for trip {data.trip_ref} with dispute {data.dispute_ref}')
    return process_extra_charge(data.trip_ref, data.dispute_ref)


@stripe_router.post('/refund')
def refund(data: Refund, token: str = Depends(get_token)):
    """

    :param data:
    :param token:
    :return:
    """
    app_logger.info(f'Refund for trip {data.trip_ref} with amount {data.amount}')
    return handle_refund(data.trip_ref, data.amount)


@stripe_router.post('/cancel_refund')
def cancel_refund(data: CancelRefund, token: str = Depends(get_token)):
    if data.full_refund:
        app_logger.info(f'Full refund for trip {data.trip_ref}')
    else:
        app_logger.info(f'Partial refund for trip {data.trip_ref}')
    return process_cancel_refund(data.trip_ref, data.full_refund)
