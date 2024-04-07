from datetime import datetime

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
    propertyRef: str
    tripBeginDateTime: datetime
    tripEndDateTime: datetime
    eventId: str


class DeleteWebhookChannel(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    id: str
    resourceId: str


class UnauthorizedMessage(BaseModel, plugin_settings=PluginSettings(logfire={'record': 'all'})):
    detail: str = 'Bearer token missing or unknown'
