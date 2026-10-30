from decimal import Decimal

import pytest
import yaml

from paysentinel.policy_config import (
    PolicyConfigurationError,
    load_policy,
)


PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
DEFAULT_POLICY = PROJECT_ROOT / "config" / "policy.yaml"


def test_loads_valid_policy():
    policy = load_policy(DEFAULT_POLICY)

    assert policy.version == "1.0.0"
    assert policy.currency == "USD"
    assert policy.payment_limits.max_single_payment == Decimal("1000.00")
    assert policy.payment_limits.daily_global_limit == Decimal("5000.00")
    assert policy.payment_limits.daily_supplier_limit == Decimal("2000.00")
    assert policy.supplier_controls.require_allowlist is True


def test_missing_policy_file_fails_closed(tmp_path):
    with pytest.raises(PolicyConfigurationError):
        load_policy(tmp_path / "missing.yaml")


def test_missing_required_limit_is_rejected(tmp_path):
    raw = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    del raw["policy"]["payment_limits"]["max_single_payment"]

    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(PolicyConfigurationError, match="max_single_payment"):
        load_policy(path)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-1", "0"])
def test_invalid_payment_limit_is_rejected(tmp_path, value):
    raw = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    raw["policy"]["payment_limits"]["max_single_payment"] = value

    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(PolicyConfigurationError):
        load_policy(path)


def test_boolean_is_not_accepted_as_money(tmp_path):
    raw = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    raw["policy"]["payment_limits"]["max_single_payment"] = True

    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(PolicyConfigurationError):
        load_policy(path)


def test_invalid_boolean_setting_is_rejected(tmp_path):
    raw = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    raw["policy"]["supplier_controls"]["require_allowlist"] = "yes"

    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(PolicyConfigurationError, match="true or false"):
        load_policy(path)


def test_unsupported_currency_is_rejected(tmp_path):
    raw = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    raw["policy"]["currency"] = "EUR"

    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(PolicyConfigurationError, match="USD"):
        load_policy(path)


def test_excess_decimal_precision_is_rejected(tmp_path):
    raw = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    raw["policy"]["payment_limits"]["max_single_payment"] = "100.001"

    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(PolicyConfigurationError, match="two decimal places"):
        load_policy(path)