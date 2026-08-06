"""Deterministic Decimal-based supplier recommendation policy engine."""

from copy import deepcopy
from decimal import Decimal

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchase_policy import ProductPurchasePolicy, ProductSupplierAssessment


DEFAULT_POLICY = {
    "selection_mode": "best_eligible_price",
    "preferred_supplier_id": None,
    "minimum_quality": 1,
    "max_price_premium_percent": Decimal("0"),
    "max_price_premium_absolute": Decimal("0"),
    "allow_spot": True,
    "scope": "default",
}


def decimal_value(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def assessment_snapshot(row: ProductSupplierAssessment) -> dict:
    return {
        "id": row.id,
        "product_id": row.product_id,
        "supplier_id": row.supplier_id,
        "location_id": row.location_id,
        "status": row.status,
        "quality_score": row.quality_score,
        "reason": row.reason,
        "scope": "location" if row.location_id is not None else "global",
    }


def policy_snapshot(row: ProductPurchasePolicy | None) -> dict:
    if row is None:
        return dict(DEFAULT_POLICY)
    return {
        "id": row.id,
        "product_id": row.product_id,
        "location_id": row.location_id,
        "selection_mode": row.selection_mode,
        "preferred_supplier_id": row.preferred_supplier_id,
        "minimum_quality": row.minimum_quality,
        "max_price_premium_percent": decimal_value(row.max_price_premium_percent),
        "max_price_premium_absolute": decimal_value(row.max_price_premium_absolute),
        "allow_spot": row.allow_spot,
        "notes": row.notes,
        "scope": "location" if row.location_id is not None else "global",
    }


async def load_effective_purchase_context(
    db: AsyncSession, product_id: int, location_id: int | None
) -> tuple[dict[int, dict], dict]:
    assessment_filter = ProductSupplierAssessment.location_id.is_(None)
    policy_filter = ProductPurchasePolicy.location_id.is_(None)
    if location_id is not None:
        assessment_filter = or_(
            ProductSupplierAssessment.location_id == location_id,
            ProductSupplierAssessment.location_id.is_(None),
        )
        policy_filter = or_(
            ProductPurchasePolicy.location_id == location_id,
            ProductPurchasePolicy.location_id.is_(None),
        )

    assessments = (
        await db.scalars(
            select(ProductSupplierAssessment)
            .where(
                ProductSupplierAssessment.product_id == product_id,
                assessment_filter,
            )
            .order_by(
                case((ProductSupplierAssessment.location_id.is_not(None), 0), else_=1),
                ProductSupplierAssessment.id.desc(),
            )
        )
    ).all()
    effective_assessments: dict[int, dict] = {}
    for row in assessments:
        effective_assessments.setdefault(row.supplier_id, assessment_snapshot(row))

    policy = await db.scalar(
        select(ProductPurchasePolicy)
        .where(ProductPurchasePolicy.product_id == product_id, policy_filter)
        .order_by(
            case((ProductPurchasePolicy.location_id.is_not(None), 0), else_=1),
            ProductPurchasePolicy.id.desc(),
        )
        .limit(1)
    )
    return effective_assessments, policy_snapshot(policy)


def rank_supplier_offers(
    offers: list[dict],
    assessments: dict[int, dict] | None = None,
    policy: dict | None = None,
) -> dict:
    """Return cheapest, recommended and selected offers without float arithmetic."""
    assessments = assessments or {}
    effective_policy = {**DEFAULT_POLICY, **(policy or {})}
    effective_policy["minimum_quality"] = int(effective_policy["minimum_quality"])
    effective_policy["max_price_premium_percent"] = decimal_value(
        effective_policy["max_price_premium_percent"]
    )
    effective_policy["max_price_premium_absolute"] = decimal_value(
        effective_policy["max_price_premium_absolute"]
    )

    ranked: list[dict] = []
    for raw in offers:
        offer = deepcopy(raw)
        supplier_id = int(offer["supplier_id"])
        assessment = assessments.get(supplier_id) or {
            "status": "approved",
            "quality_score": 3,
            "reason": None,
            "scope": "default",
        }
        status = assessment.get("status", "approved")
        quality = int(assessment.get("quality_score", 3))
        exclusions: list[str] = []
        if status == "blocked":
            exclusions.append("blocked_supplier")
        elif status == "discouraged":
            exclusions.append("discouraged_supplier")
        if quality < effective_policy["minimum_quality"]:
            exclusions.append("quality_below_minimum")
        if offer.get("source_type") == "spot" and not effective_policy["allow_spot"]:
            exclusions.append("spot_not_allowed")

        offer["assessment"] = assessment
        offer["eligible"] = not exclusions
        offer["exclusion_reasons"] = exclusions
        offer["_unit_price"] = decimal_value(offer["unit_price_normalized"])
        ranked.append(offer)

    ranked.sort(key=lambda item: (item["_unit_price"], int(item["supplier_id"])))
    absolute = ranked[0] if ranked else None
    eligible = [item for item in ranked if item["eligible"]]
    recommended = None
    reason = "no_valid_offer"

    if eligible:
        cheapest_eligible = eligible[0]
        mode = effective_policy["selection_mode"]
        preferred_id = effective_policy.get("preferred_supplier_id")
        if mode == "absolute_lowest":
            recommended = cheapest_eligible
            reason = "absolute_lowest_eligible"
        else:
            base = cheapest_eligible["_unit_price"]
            percent_cap = base * (
                Decimal("1")
                + effective_policy["max_price_premium_percent"] / Decimal("100")
            )
            absolute_cap = base + effective_policy["max_price_premium_absolute"]
            cap = max(base, percent_cap, absolute_cap)
            within_premium = [item for item in eligible if item["_unit_price"] <= cap]
            preferred = next(
                (
                    item
                    for item in within_premium
                    if preferred_id is not None and int(item["supplier_id"]) == int(preferred_id)
                ),
                None,
            )
            if preferred:
                recommended = preferred
                reason = "preferred_supplier_within_premium"
            elif cap > base:
                recommended = min(
                    within_premium,
                    key=lambda item: (
                        -int(item["assessment"].get("quality_score", 3)),
                        item["_unit_price"],
                        int(item["supplier_id"]),
                    ),
                )
                reason = (
                    "quality_within_premium"
                    if recommended is not cheapest_eligible
                    else "best_eligible_price"
                )
            else:
                recommended = cheapest_eligible
                reason = "best_eligible_price"

    requires_manual = effective_policy["selection_mode"] == "manual"
    selected = None if requires_manual else recommended
    for offer in ranked:
        offer["is_absolute_cheapest"] = absolute is offer
        offer["is_recommended"] = recommended is offer
        offer["is_selected"] = selected is offer
        offer.pop("_unit_price", None)

    serializable_policy = {
        **effective_policy,
        "max_price_premium_percent": str(effective_policy["max_price_premium_percent"]),
        "max_price_premium_absolute": str(effective_policy["max_price_premium_absolute"]),
    }
    return {
        "absolute_cheapest": absolute,
        "recommended_offer": recommended,
        "selected_offer": selected,
        "offers": ranked,
        "policy": serializable_policy,
        "recommendation_reason": reason,
        "requires_manual_selection": requires_manual,
        "warnings": [] if recommended else ["Nessuna offerta rispetta le regole di acquisto."],
    }
