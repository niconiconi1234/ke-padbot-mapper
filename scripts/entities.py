from pydantic import BaseModel
from typing import Optional


class Property(BaseModel):
    name: Optional[str] = None
    dataType: Optional[str] = None
    description: Optional[str] = None
    accessMode: Optional[str] = None
    defaultValue: Optional[object] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    unit: Optional[str] = None


class DeviceModel(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    properties: list[Property]


class DeviceInstance(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    protocol: Optional[str] = None
    model: Optional[str] = None


class DeviceProfiles(BaseModel):
    deviceModels: list[DeviceModel]
    deviceInstances: list[DeviceInstance]


class DeviceStateUpdate(BaseModel):
    state: str


class BaseMessage(BaseModel):
    event_id: Optional[str] = None
    timestamp: Optional[int] = None


class ValueMetadata(BaseModel):
    timestamp: Optional[int] = None


class TypeMetadata(BaseModel):
    type: Optional[str] = None


class TwinValue(BaseModel):
    value: Optional[object] = None
    metadata: Optional[ValueMetadata] = None


class TwinVersion(BaseModel):
    cloud: Optional[int] = None
    edge: Optional[int] = None


class MsgTwin(BaseModel):
    expected: Optional[TwinValue] = None
    actual: Optional[TwinValue] = None
    optional: Optional[bool] = None
    metadata: Optional[TypeMetadata] = None
    expected_version: Optional[TwinVersion] = None
    actual_version: Optional[TwinVersion] = None


class DeviceTwinUpdate(BaseModel):
    base_message: Optional[BaseMessage] = None
    twin: Optional[dict[str, MsgTwin]] = None
