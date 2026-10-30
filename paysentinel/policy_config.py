"""Validated configuration loader for PaySentinel AI security policies."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


class PolicyConfigurationError(ValueError):
    """Raised when a security policy is missing or invalid."""


@dataclass(frozen=True)
class PaymentLimits:
    max_single_payment: Decimal
    daily_global_limit: Decimal
    daily_supplier_limit: Decimal


@dataclass(frozen=True)
class SupplierControls:
    require_allowlist: bool
    require_active_status: bool
    bank_change_requires_approval: bool


@dataclass(frozen=True)
class InvoiceControls:
    require_purchase_order: bool
    require_goods_received: bool
    detect_duplicate_invoice_numbers: bool


@dataclass(frozen=True)
class PolicyConfig:
    version: str
    currency: str
    payment_limits: PaymentLimits
    supplier_controls: SupplierControls
    invoice_controls: InvoiceControls


def _required_mapping(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise PolicyConfigurationError(
            f"Policy field '{field}' must be a mapping."
        )
    return value


def _required_value(mapping: dict, key: str, parent: str) -> Any:
    if key not in mapping:
        raise PolicyConfigurationError(
            f"Missing required policy field: {parent}.{key}"
        )
    return mapping[key]


def _positive_money(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise PolicyConfigurationError(
            f"Policy field '{field}' must be a monetary amount."
        )

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise PolicyConfigurationError(
            f"Policy field '{field}' must be a valid decimal amount."
        ) from None

    if not amount.is_finite() or amount <= 0:
        raise PolicyConfigurationError(
            f"Policy field '{field}' must be finite and greater than zero."
        )

    # Reject amounts with more than two decimal places for this USD policy.
    if amount != amount.quantize(Decimal("0.01")):
        raise PolicyConfigurationError(
            f"Policy field '{field}' cannot have more than two decimal places."
        )

    return amount


def _required_bool(mapping: dict, key: str, parent: str) -> bool:
    value = _required_value(mapping, key, parent)

    if not isinstance(value, bool):
        raise PolicyConfigurationError(
            f"Policy field '{parent}.{key}' must be true or false."
        )

    return value


def load_policy(path: str | Path) -> PolicyConfig:
    """Load and validate policy configuration; never silently default rules."""
    policy_path = Path(path)

    try:
        with policy_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file)
    except FileNotFoundError:
        raise PolicyConfigurationError(
            f"Policy configuration file not found: {policy_path}"
        ) from None
    except yaml.YAMLError as error:
        raise PolicyConfigurationError(
            f"Invalid YAML policy configuration: {error}"
        ) from None
    except OSError as error:
        raise PolicyConfigurationError(
            f"Unable to read policy configuration: {error}"
        ) from None

    root = _required_mapping(raw, "root")
    policy = _required_mapping(
        _required_value(root, "policy", "root"),
        "policy",
    )

    version = _required_value(policy, "version", "policy")
    currency = _required_value(policy, "currency", "policy")

    if not isinstance(version, str) or not version.strip():
        raise PolicyConfigurationError(
            "Policy version must be a non-empty string."
        )

    if not isinstance(currency, str) or currency != "USD":
        raise PolicyConfigurationError(
            "This initial implementation supports USD policies only."
        )

    limits_raw = _required_mapping(
        _required_value(policy, "payment_limits", "policy"),
        "policy.payment_limits",
    )
    supplier_raw = _required_mapping(
        _required_value(policy, "supplier_controls", "policy"),
        "policy.supplier_controls",
    )
    invoice_raw = _required_mapping(
        _required_value(policy, "invoice_controls", "policy"),
        "policy.invoice_controls",
    )

    limits = PaymentLimits(
        max_single_payment=_positive_money(
            _required_value(
                limits_raw,
                "max_single_payment",
                "policy.payment_limits",
            ),
            "policy.payment_limits.max_single_payment",
        ),
        daily_global_limit=_positive_money(
            _required_value(
                limits_raw,
                "daily_global_limit",
                "policy.payment_limits",
            ),
            "policy.payment_limits.daily_global_limit",
        ),
        daily_supplier_limit=_positive_money(
            _required_value(
                limits_raw,
                "daily_supplier_limit",
                "policy.payment_limits",
            ),
            "policy.payment_limits.daily_supplier_limit",
        ),
    )

    supplier_controls = SupplierControls(
        require_allowlist=_required_bool(
            supplier_raw,
            "require_allowlist",
            "policy.supplier_controls",
        ),
        require_active_status=_required_bool(
            supplier_raw,
            "require_active_status",
            "policy.supplier_controls",
        ),
        bank_change_requires_approval=_required_bool(
            supplier_raw,
            "bank_change_requires_approval",
            "policy.supplier_controls",
        ),
    )

    invoice_controls = InvoiceControls(
        require_purchase_order=_required_bool(
            invoice_raw,
            "require_purchase_order",
            "policy.invoice_controls",
        ),
        require_goods_received=_required_bool(
            invoice_raw,
            "require_goods_received",
            "policy.invoice_controls",
        ),
        detect_duplicate_invoice_numbers=_required_bool(
            invoice_raw,
            "detect_duplicate_invoice_numbers",
            "policy.invoice_controls",
        ),
    )

    return PolicyConfig(
        version=version,
        currency=currency,
        payment_limits=limits,
        supplier_controls=supplier_controls,
        invoice_controls=invoice_controls,
    )