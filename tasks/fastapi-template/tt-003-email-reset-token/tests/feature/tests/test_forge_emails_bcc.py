"""EMAILS_BCC must accept the list spellings operators actually write."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
CANONICAL = ["audit@example.com", "ops@example.com"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("EMAILS_BCC", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(bad: str, **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    message = str(exc.value)
    assert "EMAILS_BCC" in message, message
    assert bad in message, message


def test_default_is_empty_list() -> None:
    assert make().EMAILS_BCC == []


def test_python_list_still_works() -> None:
    assert make(EMAILS_BCC=list(CANONICAL)).EMAILS_BCC == CANONICAL


def test_other_settings_unchanged() -> None:
    s = make()
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 48
    assert s.emails_enabled is False


def test_fault_csv_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", "audit@example.com, ops@example.com")
    assert make().EMAILS_BCC == CANONICAL


@pytest.mark.parametrize(
    "value",
    [
        "audit@example.com,ops@example.com",
        "  audit@example.com ,  ops@example.com  ",
        "audit@example.com, ops@example.com,",
    ],
)
def test_fault_csv_list_kwarg(value: str) -> None:
    assert make(EMAILS_BCC=value).EMAILS_BCC == CANONICAL


def test_fault_csv_list_single_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", "audit@example.com")
    assert make().EMAILS_BCC == ["audit@example.com"]


def test_fault_json_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", '["audit@example.com", "ops@example.com"]')
    assert make().EMAILS_BCC == CANONICAL


def test_fault_json_list_kwarg() -> None:
    value = '  ["audit@example.com","ops@example.com"] '
    assert make(EMAILS_BCC=value).EMAILS_BCC == CANONICAL


@pytest.mark.parametrize("value", ["", "   ", "[]"])
def test_fault_empty_list_kwarg(value: str) -> None:
    assert make(EMAILS_BCC=value).EMAILS_BCC == []


def test_fault_empty_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", "")
    assert make().EMAILS_BCC == []


def test_fault_garbage_bad_address_in_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", "audit@example.com, not-an-email")
    with pytest.raises(ValueError) as exc:
        make()
    message = str(exc.value)
    assert "EMAILS_BCC" in message, message
    assert "not-an-email" in message, message


def test_fault_garbage_bad_address_kwarg() -> None:
    assert_rejected("not-an-email", EMAILS_BCC="audit@example.com, not-an-email")


def test_fault_garbage_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", '["audit@example.com", ')
    with pytest.raises(ValueError) as exc:
        make()
    message = str(exc.value)
    assert "EMAILS_BCC" in message, message
    assert '["audit@example.com",' in message, message


def test_fault_garbage_non_string_json_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAILS_BCC", '["audit@example.com", 42]')
    with pytest.raises(ValueError) as exc:
        make()
    message = str(exc.value)
    assert "EMAILS_BCC" in message, message
    assert "42" in message, message
