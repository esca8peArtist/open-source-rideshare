"""Pydantic schemas for Corporate Address Book."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CorporateAddressCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    address_line_1: str = Field(..., min_length=1, max_length=500)
    address_line_2: Optional[str] = Field(None, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    zip_code: Optional[str] = Field(None, max_length=20)
    country: str = Field("US", min_length=2, max_length=2)
    latitude: Optional[Decimal] = Field(None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(None, ge=-180, le=180)
    notes: Optional[str] = None
    is_pickup_point: bool = True
    is_dropoff_point: bool = True
    default_cost_center_id: Optional[int] = None
    default_trip_purpose_id: Optional[int] = None


class CorporateAddressUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address_line_1: Optional[str] = Field(None, min_length=1, max_length=500)
    address_line_2: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, min_length=1, max_length=100)
    state: Optional[str] = Field(None, min_length=1, max_length=100)
    zip_code: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, min_length=2, max_length=2)
    latitude: Optional[Decimal] = Field(None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(None, ge=-180, le=180)
    notes: Optional[str] = None
    is_pickup_point: Optional[bool] = None
    is_dropoff_point: Optional[bool] = None
    default_cost_center_id: Optional[int] = None
    default_trip_purpose_id: Optional[int] = None


class CorporateAddressResponse(BaseModel):
    id: int
    account_id: int
    name: str
    address_line_1: str
    address_line_2: Optional[str]
    city: str
    state: str
    zip_code: Optional[str]
    country: str
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]
    notes: Optional[str]
    is_pickup_point: bool
    is_dropoff_point: bool
    default_cost_center_id: Optional[int]
    default_trip_purpose_id: Optional[int]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CorporateAddressListResponse(BaseModel):
    addresses: list[CorporateAddressResponse]
    total: int
