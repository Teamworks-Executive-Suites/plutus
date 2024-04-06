from datetime import datetime

from pydantic import BaseModel, Field


class Name(BaseModel):
    name: str


class CancelRefund(BaseModel):
    trip_ref: str
    full_refund: bool


class ExtraCharge(BaseModel):
    trip_ref: str
    dispute_ref: str


class Refund(BaseModel):
    trip_ref: str
    amount: int


class PropertyCal(BaseModel):
    property_ref: str
    cal_id: str

class TripCal(BaseModel):
    cal_id: str
    trip_ref: str

class Event(BaseModel):
    kind: str = Field(..., regex="^calendar#event$")
    id: str
    status: str
    created: datetime
    updated: datetime
    start: dict
    end: dict

class TripData(BaseModel):
    isExternal: bool
    propertyRef: str
    tripBeginDateTime: datetime
    tripEndDateTime: datetime
    eventId: str




class UnauthorizedMessage(BaseModel):
    detail: str = 'Bearer token missing or unknown'
