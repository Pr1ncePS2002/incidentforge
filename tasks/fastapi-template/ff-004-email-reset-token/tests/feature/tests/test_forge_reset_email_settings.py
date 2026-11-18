"""startup checks for settings that password-recovery email depends on."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
ENV_VARS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_TLS",
    "SMTP_SSL",
    "EMAILS_FROM_EMAIL",
    "EMAILS_FROM_NAME",
    "FRONTEND_HOST",
    "EMAIL_RESET_TOKEN_EXPIRE_HOURS",
)
GOOD_EMAIL = {
    "SMTP_HOST": "smtp.example.com",
    "EMAILS_FROM_EMAIL": "info@example.com",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_shipped_defaults_still_load() -> None:
    s = make()
    assert s.SMTP_HOST is None
    assert s.emails_enabled is False
    assert s.FRONTEND_HOST == "http://localhost:5173"
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 48


def test_email_without_credentials_loads() -> None:
    s = make(**GOOD_EMAIL)
    assert s.emails_enabled is True


def test_complete_email_config_loads() -> None:
    s = make(
        **GOOD_EMAIL,
        SMTP_USER="mailer",
        SMTP_PASSWORD="real-mailer-pw",
        FRONTEND_HOST="https://dashboard.example.com",
    )
    assert s.emails_enabled is True
    assert s.SMTP_PASSWORD == "real-mailer-pw"


def test_unused_mail_settings_ignored_when_email_disabled() -> None:
    s = make(SMTP_PASSWORD="changethis")
    assert s.emails_enabled is False


def test_fault_conditional_missing_from_email() -> None:
    assert_rejected(["EMAILS_FROM_EMAIL"], SMTP_HOST="smtp.example.com")


def test_fault_conditional_missing_smtp_password() -> None:
    assert_rejected(["SMTP_PASSWORD"], **GOOD_EMAIL, SMTP_USER="mailer")


def test_fault_empty_smtp_host() -> None:
    assert_rejected(
        ["SMTP_HOST"], SMTP_HOST="   ", EMAILS_FROM_EMAIL="info@example.com"
    )


def test_fault_empty_frontend_host() -> None:
    assert_rejected(["FRONTEND_HOST"], **GOOD_EMAIL, FRONTEND_HOST="  ")


def test_fault_empty_smtp_password() -> None:
    assert_rejected(
        ["SMTP_PASSWORD"], **GOOD_EMAIL, SMTP_USER="mailer", SMTP_PASSWORD=" "
    )


@pytest.mark.parametrize("value", ["changethis", "TODO", "<fill-me>", " ChangeThis "])
def test_fault_placeholder_smtp_password(value: str) -> None:
    assert_rejected(
        ["SMTP_PASSWORD"], **GOOD_EMAIL, SMTP_USER="mailer", SMTP_PASSWORD=value
    )


def test_fault_placeholder_frontend_host() -> None:
    assert_rejected(["FRONTEND_HOST"], **GOOD_EMAIL, FRONTEND_HOST="<fill-me>")


def test_fault_placeholder_smtp_host() -> None:
    assert_rejected(
        ["SMTP_HOST"], SMTP_HOST="changethis", EMAILS_FROM_EMAIL="info@example.com"
    )


def test_fault_several_bad() -> None:
    assert_rejected(
        ["EMAILS_FROM_EMAIL", "FRONTEND_HOST", "SMTP_PASSWORD"],
        SMTP_HOST="smtp.example.com",
        FRONTEND_HOST="  ",
        SMTP_USER="mailer",
        SMTP_PASSWORD="changethis",
    )
