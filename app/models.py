from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field


class Name(BaseModel):
    name: str


class CancelRefund(BaseModel):
    trip_ref: str
    full_refund: bool
    actor_ref: str


class ExtraCharge(BaseModel):
    trip_ref: str
    dispute_ref: str
    actor_ref: str


class Refund(BaseModel):
    trip_ref: str
    amount: int
    actor_ref: str


class OffSessionPayment(BaseModel):
    customer_id: str  # Guest email (will lookup Stripe customer)
    amount: int  # Amount in cents
    currency: str = 'usd'
    trip_ref: str
    guest_email: str


class PropertyCal(BaseModel):
    property_ref: str
    cal_id: str


class TripCal(BaseModel):
    cal_id: str
    trip_ref: str


class Event(BaseModel):
    kind: str = Field(..., pattern='^calendar#event$')
    id: str
    status: str
    created: datetime
    updated: datetime
    start: dict
    end: dict


class TripData(BaseModel):
    tripCreated: datetime
    isExternal: bool
    isInquiry: bool
    propertyRef: Any
    tripBeginDateTime: datetime
    tripDate: datetime
    tripEndDateTime: datetime
    eventId: str
    eventSummary: str


class EventFromTrip(BaseModel):
    trip_ref: str
    property_ref: str


class PropertyRef(BaseModel):
    property_ref: str


class DeleteWebhookChannel(BaseModel):
    id: str
    resourceId: str


class UnauthorizedMessage(BaseModel):
    detail: str = 'Bearer token missing or unknown'


class Creator(BaseModel):
    email: str


class Organizer(BaseModel):
    email: str
    displayName: str
    self: bool


class DateTime(BaseModel):
    dateTime: str
    timeZone: str


class Date(BaseModel):
    date: str


class Reminders(BaseModel):
    useDefault: bool


class GCalEvent(BaseModel):
    kind: str
    etag: str
    id: str
    status: str
    htmlLink: str
    created: str
    updated: str
    summary: Optional[str]
    creator: Creator
    organizer: Organizer
    start: Union[DateTime, Date]
    end: Union[DateTime, Date]
    iCalUID: str
    sequence: int
    reminders: Reminders
    eventType: str


class CancelledGCalEvent(BaseModel):
    kind: str
    etag: str
    id: str
    status: str


class ActorRole(str, Enum):
    platform = 'platform'
    client = 'client'
    host = 'host'


class Status(str, Enum):
    completed = 'completed'
    in_escrow = 'in_escrow'
    failed = 'failed'
    merged = 'merged'


class TransactionType(str, Enum):
    payment = 'payment'
    transfer = 'transfer'
    refund = 'refund'


class Transaction(BaseModel):
    actorRef: str
    actorRole: ActorRole
    receiverRef: str
    receiverRole: ActorRole
    transferId: Optional[str]
    status: Status
    type: TransactionType
    createdAt: datetime
    processedAt: datetime
    notes: Optional[str]
    guestFeeCents: Optional[int]
    hostFeeCents: Optional[int]
    netFeeCents: Optional[int]
    grossFeeCents: Optional[int]
    tripRef: str
    refundedAmountCents: Optional[int]
    paymentIntentIds: Optional[List[str]]
    mergedTransactions: Optional[List[str]]

    def to_dict(self):
        return self.model_dump()
