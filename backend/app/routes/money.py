"""
The money columns: in, stuck, out.

The dashboard reads /api/money-flow. The expense endpoints exist because the
spoken path needs a typed twin: a merchant fixing the books later, and a demo
running without a microphone, both need a way in.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import ExpenseRequest
from ..services import expenses, money_flow
from .deps import contexts, demand_summary, merchant, week_events

router = APIRouter(prefix="/api", tags=["money"])


@router.get("/money-flow")
def get_money_flow() -> dict:
    ctx, _ = contexts()
    profile = merchant()
    demand = demand_summary(ctx, week_events(ctx))
    return money_flow.money_flow(ctx, demand, profile["merchant_id"])


@router.get("/expenses")
def get_expenses(limit: int = 50) -> dict:
    profile = merchant()
    merchant_id = profile["merchant_id"]
    return {
        "expenses": expenses.list_expenses(merchant_id, limit=limit),
        "totals": expenses.totals(merchant_id),
        "categories": [
            {"key": key, "label": label} for key, label in expenses.CATEGORIES.items()
        ],
    }


@router.post("/expenses", status_code=201)
def post_expense(request: ExpenseRequest) -> dict:
    """Record one spend. The category is inferred from the note when not given."""
    if request.category and request.category not in expenses.CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown category '{request.category}'. "
                f"Use one of: {', '.join(expenses.CATEGORIES)}."
            ),
        )

    profile = merchant()
    row = expenses.record(
        request.amount,
        transcript=request.note,
        merchant_id=request.merchant_id or profile["merchant_id"],
        payee=request.payee,
        category=request.category,
        source="manual",
    )
    return {
        "status": "recorded",
        "expense_id": row["expense_id"],
        "message": f"₹{row['amount']:,.0f} recorded as {expenses.CATEGORIES[row['category']]}.",
        "expense": row,
        "totals": expenses.totals(row["merchant_id"]),
    }
