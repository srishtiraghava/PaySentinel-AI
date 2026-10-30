
import json
from pathlib import Path

import pytest

from paysentinel.policy_gateway import evaluate_invoice


RECORDS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "records.json"
)


def load_modified_records(tmp_path, modification):
    """Create a temporary copy of trusted records and modify it for a test."""
    records = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
    modification(records)

    path = tmp_path / "records.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def test_valid_invoice_is_eligible_for_review():
    decision = evaluate_invoice(RECORDS_PATH, "INV-2026-001")

    assert decision.outcome == "ELIGIBLE_FOR_REVIEW"
    assert decision.policy_version != "unknown"


def test_over_limit_invoice_is_blocked():
    decision = evaluate_invoice(RECORDS_PATH, "INV-2026-002")

    assert decision.outcome == "BLOCK"
    assert any(
        "maximum single-payment limit" in reason.lower()
        for reason in decision.reasons
    )


def test_bank_detail_change_requires_approval(tmp_path):
    def modify(records):
        # Keep the invoice and purchase order consistent and below $1,000.
        records["invoices"][1]["amount"] = "950.00"
        records["purchase_orders"][1]["amount"] = "950.00"

    path = load_modified_records(tmp_path, modify)
    decision = evaluate_invoice(path, "INV-2026-002")

    assert decision.outcome == "REQUIRES_APPROVAL"
    assert any(
        "bank details" in reason.lower()
        for reason in decision.reasons
    )


def test_unallowlisted_supplier_is_blocked():
    decision = evaluate_invoice(RECORDS_PATH, "INV-2026-003")

    assert decision.outcome == "BLOCK"
    assert any(
        "allowlisted" in reason.lower()
        for reason in decision.reasons
    )


def test_missing_invoice_is_blocked():
    decision = evaluate_invoice(RECORDS_PATH, "INV-DOES-NOT-EXIST")

    assert decision.outcome == "BLOCK"


def test_invoice_amount_must_match_purchase_order(tmp_path):
    def modify(records):
        records["invoices"][0]["amount"] = "700.00"

    path = load_modified_records(tmp_path, modify)
    decision = evaluate_invoice(path, "INV-2026-001")

    assert decision.outcome == "BLOCK"
    assert any(
        "purchase order" in reason.lower()
        and "amount" in reason.lower()
        for reason in decision.reasons
    )


def test_duplicate_invoice_number_is_blocked(tmp_path):
    def modify(records):
        records["invoices"][1]["number"] = records["invoices"][0]["number"]

    path = load_modified_records(tmp_path, modify)
    decision = evaluate_invoice(path, "INV-2026-001")

    assert decision.outcome == "BLOCK"
    assert any(
        "duplicate invoice number" in reason.lower()
        for reason in decision.reasons
    )


def test_goods_not_received_is_blocked(tmp_path):
    def modify(records):
        records["purchase_orders"][0]["goods_received"] = False

    path = load_modified_records(tmp_path, modify)
    decision = evaluate_invoice(path, "INV-2026-001")

    assert decision.outcome == "BLOCK"
    assert any(
        "received" in reason.lower()
        for reason in decision.reasons
    )


def test_inactive_supplier_is_blocked(tmp_path):
    def modify(records):
        records["suppliers"][0]["status"] = "inactive"

    path = load_modified_records(tmp_path, modify)
    decision = evaluate_invoice(path, "INV-2026-001")

    assert decision.outcome == "BLOCK"
    assert any(
        "not active" in reason.lower()
        for reason in decision.reasons
    )


def test_missing_policy_configuration_fails_closed(tmp_path):
    missing_policy = tmp_path / "missing_policy.yaml"

    with pytest.raises(Exception):
        evaluate_invoice(
            RECORDS_PATH,
            "INV-2026-001",
            policy_path=missing_policy,
        )
