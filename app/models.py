from datetime import datetime
from typing import Any, Optional, Union

from logfire.integrations.pydantic_plugin import PluginSettings
from pydantic import BaseModel, Field


class Name(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    name: str


class CancelRefund(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    trip_ref: str
    full_refund: bool


class ExtraCharge(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    trip_ref: str
    dispute_ref: str


class Refund(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    trip_ref: str
    amount: int


class PropertyCal(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    property_ref: str
    cal_id: str


class TripCal(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    cal_id: str
    trip_ref: str


class Event(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    kind: str = Field(..., pattern='^calendar#event$')
    id: str
    status: str
    created: datetime
    updated: datetime
    start: dict
    end: dict


class TripData(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    isExternal: bool
    isInquiry: bool
    propertyRef: Any
    tripBeginDateTime: datetime
    tripDate: datetime
    tripEndDateTime: datetime
    eventId: str
    eventSummary: str


class EventFromTrip(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    trip_ref: str
    property_ref: str


class PropertyRef(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    property_ref: str


class DeleteWebhookChannel(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    id: str
    resourceId: str


class UnauthorizedMessage(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    detail: str = 'Bearer token missing or unknown'


class Creator(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    email: str


class Organizer(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    email: str
    displayName: str
    self: bool


class DateTime(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    dateTime: str
    timeZone: str


class Date(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    date: str


class Reminders(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    useDefault: bool


class GCalEvent(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
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


class CancelledGCalEvent(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    kind: str
    etag: str
    id: str
    status: str
