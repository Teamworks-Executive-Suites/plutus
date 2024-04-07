from fastapi import APIRouter, Depends

from app.auth.views import get_token
from app.models import CancelRefund, ExtraCharge, Refund
from app.pay._utils import app_logger
from app.pay.tasks import handle_refund, process_cancel_refund, process_extra_charge

stripe_router = APIRouter()


@stripe_router.post('/extra_charge')
def extra_charge(data: ExtraCharge, token: str = Depends(get_token)):
    app_logger.info('Extra charge for trip %s with dispute %s', data.trip_ref, data.dispute_ref)
    return process_extra_charge(data.trip_ref, data.dispute_ref)


@stripe_router.post('/refund')
def refund(data: Refund, token: str = Depends(get_token)):
    """

    :param data:
    :param token:
    :return:
    """
    app_logger.info('Refund for trip %s with amount %s', data.trip_ref, data.amount)
    return handle_refund(data.trip_ref, data.amount)


@stripe_router.post('/cancel_refund')
def cancel_refund(data: CancelRefund, token: str = Depends(get_token)):
    if data.full_refund:
        app_logger.info('Full refund for trip %s', data.trip_ref)
    else:
        app_logger.info('Partial refund for trip %s', data.trip_ref)
    return process_cancel_refund(data.trip_ref, data.full_refund)
