from pydantic import BaseModel


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
    cal_link: str


class UnauthorizedMessage(BaseModel):
    detail: str = 'Bearer token missing or unknown'
