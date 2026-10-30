import json

import pytest

from paysentinel.payment_ledger import DuplicatePaymentError, PaymentLedger
from paysentinel.payment_service import PaymentService


@pytest.fixture
def records_path():
    return (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "data"
        / "records.json"
    )


@pytest.fixture
def service(tmp_path, records_path):
    ledger = PaymentLedger(tmp_path / "payments.sqlite3")
    return PaymentService(records_path=records_path, ledger=ledger)


def test_valid_invoice_is_recorded_for_review(service):
    result = service.evaluate_and_record("INV-2026-001")

    assert result.decision.outcome == "ELIGIBLE_FOR_REVIEW"
    assert result.payment["status"] == "REVIEW_REQUIRED"
    assert result.payment["invoice_id"] == "INV-2026-001"


def test_over_limit_invoice_is_blocked_and_recorded(service):
    """An invoice above the configured single-payment limit must be blocked."""
    result = service.evaluate_and_record("INV-2026-002")

    assert result.decision.outcome == "BLOCK"
    assert any(
        "maximum single-payment limit" in reason.lower()
        for reason in result.decision.reasons
    )
    assert result.payment["status"] == "BLOCKED"


def test_bank_change_invoice_enters_approval_queue(tmp_path, records_path):
    """A bank-detail change requires approval when other policy checks pass."""
    records = json.loads(records_path.read_text(encoding="utf-8"))

    # Keep the invoice and its PO consistent and below the $1,000 limit.
    records["invoices"][1]["amount"] = "950.00"
    records["purchase_orders"][1]["amount"] = "950.00"

    modified_records = tmp_path / "approval_records.json"
    modified_records.write_text(
        json.dumps(records),
        encoding="utf-8",
    )

    ledger = PaymentLedger(tmp_path / "approval_payments.sqlite3")
    service = PaymentService(
        records_path=modified_records,
        ledger=ledger,
    )

    result = service.evaluate_and_record("INV-2026-002")

    assert result.decision.outcome == "REQUIRES_APPROVAL"
    assert result.payment["status"] == "PENDING_APPROVAL"

    events = ledger.get_events(result.payment["payment_id"])

    assert [event["new_status"] for event in events] == [
        "REVIEW_REQUIRED",
        "PENDING_APPROVAL",
    ]


def test_unallowlisted_supplier_is_blocked(service):
    result = service.evaluate_and_record("INV-2026-003")

    assert result.decision.outcome == "BLOCK"
    assert result.payment["status"] == "BLOCKED"
    assert any(
        "allowlisted" in reason.lower()
        for reason in result.decision.reasons
    )


def test_missing_invoice_is_blocked_and_recorded(service):
    result = service.evaluate_and_record("INV-DOES-NOT-EXIST")

    assert result.decision.outcome == "BLOCK"
    assert result.payment["status"] == "BLOCKED"


def test_duplicate_processing_is_rejected(service):
    service.evaluate_and_record("INV-2026-001")

    with pytest.raises(DuplicatePaymentError):
        service.evaluate_and_record("INV-2026-001")


def test_empty_invoice_id_is_rejected(service):
    with pytest.raises(ValueError, match="invoice_id"):
        service.evaluate_and_record("")


def test_whitespace_invoice_id_is_rejected(service):
    with pytest.raises(ValueError, match="invoice_id"):
        service.evaluate_and_record("   ")


def test_service_never_authorizes_payment(service):
    result = service.evaluate_and_record("INV-2026-001")

    assert result.payment["status"] not in {
        "AUTHORIZED",
        "SUBMITTED",
        "UNKNOWN",
    }


def test_changed_invoice_amount_is_blocked(tmp_path, records_path):
    records = json.loads(records_path.read_text(encoding="utf-8"))

    # Change the invoice amount without changing its trusted PO.
    records["invoices"][0]["amount"] = "700.00"

    modified_records = tmp_path / "changed_amount_records.json"
    modified_records.write_text(
        json.dumps(records),
        encoding="utf-8",
    )

    ledger = PaymentLedger(tmp_path / "changed_amount_payments.sqlite3")
    service = PaymentService(
        records_path=modified_records,
        ledger=ledger,
    )

    result = service.evaluate_and_record("INV-2026-001")

    assert result.decision.outcome == "BLOCK"
    assert result.payment["status"] == "BLOCKED"
    assert any(
        "purchase order" in reason.lower()
        and "amount" in reason.lower()
        for reason in result.decision.reasons
    )