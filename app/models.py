from pydantic import BaseModel


class Name(BaseModel):
    name: str


class Trip(BaseModel):
    trip_ref: str


class ExtraCharge(BaseModel):
    trip_ref: str
    dispute_ref: str


class Refund(BaseModel):
    trip_ref: str
    amount: int


class PropertyCal(BaseModel):
    property_ref: str
    cal_link: str


class UnauthorizedMessage(BaseModel):
    detail: str = 'Bearer token missing or unknown'
