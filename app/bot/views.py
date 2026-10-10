"""Data endpoints for the chatbot.

These know nothing about AI. They are ordinary JSON endpoints that happen to be
called by a tool in the marketing site's agent — same shape as /refund or
/event_from_trip, and testable with curl alone.

Why here and not in the website: the availability rule is a line-by-line port of
the Flutter booking page (see app/bot/tools.py), pinned by parity tests. Keeping
one implementation is the whole point — a second copy in TypeScript would drift,
and the failure mode is double-booking a paying customer.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.bot._utils import get_bot_token
from app.bot.tools import (
    check_availability,
    get_property_details,
    list_addons,
    search_properties,
)

bot_router = APIRouter(prefix='/bot', tags=['bot'])


class SearchRequest(BaseModel):
    min_capacity: int = Field(1, ge=1, le=1000)
    area: str = ''
    max_hourly_price: int = 0
    name: str = Field('', max_length=100)


class AvailabilityRequest(BaseModel):
    property_ids: list[str] = Field(..., min_length=1, max_length=10)
    start_local_iso: str
    end_local_iso: str


class DetailsRequest(BaseModel):
    property_id: str


@bot_router.post('/search_properties')
def bot_search_properties(data: SearchRequest, token: str = Depends(get_bot_token)):
    return search_properties(data.min_capacity, data.area, data.max_hourly_price, data.name)


@bot_router.post('/check_availability')
def bot_check_availability(data: AvailabilityRequest, token: str = Depends(get_bot_token)):
    return check_availability(data.property_ids, data.start_local_iso, data.end_local_iso)


@bot_router.post('/property_details')
def bot_property_details(data: DetailsRequest, token: str = Depends(get_bot_token)):
    return get_property_details(data.property_id)


@bot_router.post('/list_addons')
def bot_list_addons(data: DetailsRequest, token: str = Depends(get_bot_token)):
    return list_addons(data.property_id)
