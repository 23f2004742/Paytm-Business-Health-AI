"""Request/response models for the public API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class CampaignRequest(BaseModel):
    merchant_id: str = "PAYTM_M_001"
    campaign_name: str = "Evening Boost"
    cashback_amount: int = Field(..., ge=1, le=1000)
    minimum_transaction: int = Field(..., ge=1, le=100000)
    start_time: str = Field("18:00", pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field("21:00", pattern=r"^\d{2}:\d{2}$")
    target_segment: Optional[str] = None


class CampaignResponse(BaseModel):
    status: str
    campaign_id: str
    message: str
    campaign: dict
    projection: dict


class RestockRequest(BaseModel):
    """
    Only the product is accepted. Request counts are re-read from the event
    store server-side, so a client cannot inflate the evidence behind an alert.
    """

    product: str = Field(..., min_length=1, max_length=120)
    merchant_id: Optional[str] = None


class ShopTextRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=2000)
    merchant_id: Optional[str] = None
    timestamp: Optional[str] = None
    source: str = "manual"


class ExpenseRequest(BaseModel):
    """
    A spend, typed rather than spoken.

    The voice path is the real one, but a merchant correcting the books on a
    quiet afternoon should not need to talk to the box, and a demo should not
    need a microphone.
    """

    amount: float = Field(..., gt=0, le=1_000_000)
    note: str = Field(..., min_length=1, max_length=300)
    category: Optional[str] = None
    payee: Optional[str] = Field(default=None, max_length=60)
    merchant_id: Optional[str] = None


class ReminderRequest(BaseModel):
    """Chase one customer for what they owe."""

    customer: str = Field(..., min_length=1, max_length=60)
    # A shop that nags loses the customer, so a second reminder inside the
    # cooldown has to be asked for explicitly.
    force: bool = False


class ContactRequest(BaseModel):
    """Where a khata customer is reached, and in which language."""

    customer: str = Field(..., min_length=1, max_length=60)
    phone: Optional[str] = Field(default=None, max_length=32)
    language: Optional[str] = Field(default=None, max_length=20)
