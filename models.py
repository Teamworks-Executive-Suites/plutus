from pydantic import BaseModel
from devtools import debug


class Name(BaseModel):
    name: str

class Dispute(BaseModel):
    trip_ref: str


class PropertyCal(BaseModel):
    property_ref: str
    cal_link: str


class UnauthorizedMessage(BaseModel):
    detail: str = "Bearer token missing or unknown"