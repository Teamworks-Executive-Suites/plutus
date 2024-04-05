from fastapi import APIRouter, Request

from app.cal._utils import app_logger
from app.cal.tasks import create_or_update_trip_from_event
from app.models import Event

cal_router = APIRouter()

@cal_router.post('/cal_webhook')
async def receive_webhook(request: Request, calendar_id: str):
    data = await request.json()
    if data.get('kind') != 'calendar#event':
        app_logger.info('Received non-event webhook')
    event = Event(**data)
    if calendar_id and event.id:
        create_or_update_trip_from_event(calendar_id, event)
    app_logger.info('Received event webhook')
