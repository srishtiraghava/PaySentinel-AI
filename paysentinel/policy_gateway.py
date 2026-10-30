"""Deterministic PaySentinel policy checks.

Policy decisions are based on trusted system records and a validated,
versioned policy configuration. This module never executes payments.
"""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from paysentinel.policy_config import load_policy


DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "policy.yaml"
)


@dataclass(frozen=True)
class PolicyDecision:
    invoice_id: str
    outcome: str
    reasons: tuple[str, ...]
    policy_version: str = "unknown"


def _money(value: Any) -> Decimal:
    """Parse monetary values without floating-point arithmetic."""
    if isinstance(value, bool):
        raise ValueError("Invalid monetary value")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid monetary value") from None

    if not amount.is_finite():
        raise ValueError("Monetary value must be finite")

    return amount


def evaluate_invoice(
    records_path: str | Path,
    invoice_id: str,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> PolicyDecision:
    """Evaluate an invoice against trusted records and validated policy.

    Outcomes:
      BLOCK: a mandatory policy check failed.
      REQUIRES_APPROVAL: checks passed, but human approval is required.
      ELIGIBLE_FOR_REVIEW: basic checks passed; payment is not authorized.

    Missing or invalid policy configuration raises an error. Callers must
    not proceed with payment processing when policy loading fails.
    """
    policy = load_policy(policy_path)

    def decision(outcome: str, reasons: list[str] | tuple[str, ...]):
        return PolicyDecision(
            invoice_id=invoice_id,
            outcome=outcome,
            reasons=tuple(reasons),
            policy_version=policy.version,
        )

    with Path(records_path).open("r", encoding="utf-8") as file:
        records = json.load(file)

    invoices = records.get("invoices", [])
    suppliers = records.get("suppliers", [])
    purchase_orders = records.get("purchase_orders", [])

    if not all(isinstance(items, list) for items in (
        invoices, suppliers, purchase_orders
    )):
        return decision("BLOCK", ["Trusted record collections are invalid."])

    matches = [
        invoice for invoice in invoices
        if isinstance(invoice, dict) and invoice.get("id") == invoice_id
    ]

    if len(matches) != 1:
        return decision(
            "BLOCK",
            ["Invoice must exist exactly once in trusted records."],
        )

    invoice = matches[0]
    reasons: list[str] = []
    supplier_id = invoice.get("supplier_id")

        # Duplicate invoice-number detection.
    invoice_number = str(invoice.get("number", "")).strip().casefold()

    if not invoice_number:
        reasons.append("Invoice number is missing.")
    elif policy.invoice_controls.detect_duplicate_invoice_numbers:
        duplicates = [
            item
            for item in invoices
            if isinstance(item, dict)
            and item.get("id") != invoice_id
            and str(item.get("number", "")).strip().casefold()
            == invoice_number
        ]

        if duplicates:
            reasons.append("Duplicate invoice number detected.")

    # Resolve the supplier from trusted records, not from an AI proposal.
    supplier_matches = [
        supplier for supplier in suppliers
        if isinstance(supplier, dict)
        and supplier.get("id") == supplier_id
    ]

    supplier = None

    if len(supplier_matches) != 1:
        reasons.append("Supplier must exist exactly once.")
    else:
        supplier = supplier_matches[0]

        if (
            policy.supplier_controls.require_active_status
            and supplier.get("status") != "active"
        ):
            reasons.append("Supplier is not active.")

        if (
            policy.supplier_controls.require_allowlist
            and supplier.get("allowlisted") is not True
        ):
            reasons.append("Supplier is not allowlisted.")

        if not supplier.get("payout_email"):
            reasons.append("Supplier payout email is missing.")

    # Invoice status and amount.
    if invoice.get("status") != "unpaid":
        reasons.append("Invoice is not marked unpaid.")

    try:
        invoice_amount = _money(invoice.get("amount"))

        if invoice_amount <= 0:
            reasons.append("Invoice amount must be positive.")
        elif invoice_amount > policy.payment_limits.max_single_payment:
            reasons.append(
                "Invoice amount exceeds the maximum single-payment limit "
                f"of {policy.currency} "
                f"{policy.payment_limits.max_single_payment}."
            )
    except ValueError:
        invoice_amount = None
        reasons.append("Invoice amount is invalid.")

    invoice_currency = invoice.get("currency")

    if not isinstance(invoice_currency, str) or not invoice_currency.strip():
        reasons.append("Invoice currency is missing.")
    elif invoice_currency != policy.currency:
        reasons.append(
            f"Invoice currency must match configured currency "
            f"{policy.currency}."
        )

    # Validate the purchase order when required, or whenever one is supplied.
    po_id = invoice.get("po_id")
    should_check_po = (
        policy.invoice_controls.require_purchase_order
        or bool(po_id)
    )

    if should_check_po:
        po_matches = [
            po for po in purchase_orders
            if isinstance(po, dict) and po.get("id") == po_id
        ] if po_id else []

        if len(po_matches) != 1:
            if policy.invoice_controls.require_purchase_order:
                reasons.append("A matching purchase order is required.")
            elif po_id:
                reasons.append(
                    "A supplied purchase order must exist exactly once."
                )
        else:
            purchase_order = po_matches[0]

            if purchase_order.get("supplier_id") != supplier_id:
                reasons.append(
                    "Purchase order supplier does not match invoice."
                )

            if invoice_amount is not None:
                try:
                    po_amount = _money(purchase_order.get("amount"))

                    if invoice_amount != po_amount:
                        reasons.append(
                            "Invoice amount does not match purchase order."
                        )
                except ValueError:
                    reasons.append("Purchase order amount is invalid.")

            if purchase_order.get("currency") != invoice_currency:
                reasons.append(
                    "Invoice currency does not match purchase order."
                )

            if (
                policy.invoice_controls.require_goods_received
                and purchase_order.get("goods_received") is not True
            ):
                reasons.append(
                    "Goods or services are not confirmed as received."
                )

    if reasons:
        return decision("BLOCK", reasons)

    # Bank-detail changes require approval when the policy enables this rule.
    if (
        supplier
        and policy.supplier_controls.bank_change_requires_approval
        and supplier.get("bank_changed_at")
    ):
        return decision(
            "REQUIRES_APPROVAL",
            ["Supplier bank details have a recorded change date."],
        )

    return decision(
        "ELIGIBLE_FOR_REVIEW",
        [
            "Basic invoice and supplier checks passed; "
            "payment is not authorized."
        ],
    )