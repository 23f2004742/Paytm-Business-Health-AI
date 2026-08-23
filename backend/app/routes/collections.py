"""
Collections: chasing the money that is stuck.

The only endpoints in this product that send something to a person outside the
shop, so the failure modes are reported precisely rather than flattened:

  409  the reminder should not be sent (settled account, cooldown, no number)
  502  it should have been sent and the channel failed
  201  it went

A merchant needs those to be three different answers. "Nothing happened" and
"we tried and it broke" require completely different next moves.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import ContactRequest, ReminderRequest
from ..services import collections_agent
from .deps import merchant

router = APIRouter(prefix="/api/collections", tags=["collections"])


@router.get("")
def get_collections() -> dict:
    return collections_agent.snapshot()


@router.post("/remind", status_code=201)
def post_reminder(request: ReminderRequest) -> dict:
    """Chase one customer. The message text is returned either way."""
    try:
        result = collections_agent.remind(
            request.customer,
            shop=merchant()["name"],
            force=request.force,
        )
    except collections_agent.CollectionError as exc:
        # Refused on purpose: a settled khata, a cooldown, or no phone number.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not result["delivered"]:
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"Reminder for {result['customer']} was not delivered.",
                "reason": result["detail"],
                "prepared": result["message"],
            },
        )

    return {"status": "sent", "reminder": result}


@router.post("/contact")
def post_contact(request: ContactRequest) -> dict:
    """Set where a customer is reached, and which language to write to them in."""
    try:
        customer = collections_agent.set_contact(
            request.customer, phone=request.phone, language=request.language
        )
    except collections_agent.CollectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "updated",
        "customer": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "balance": customer["balance"],
            "phone": customer.get("phone"),
            "language": customer.get("language"),
        },
    }
