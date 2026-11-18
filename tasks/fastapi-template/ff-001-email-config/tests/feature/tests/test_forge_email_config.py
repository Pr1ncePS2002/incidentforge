"""fault cases for half-configured email settings; each must fail at startup."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
EMAIL_VARS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_TLS",
    "SMTP_SSL",
    "EMAILS_FROM_EMAIL",
    "EMAILS_FROM_NAME",
)


@pytest.fixture(autouse=True)
def _clean_email_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # only the overrides passed by each test may configure email
    for name in EMAIL_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_no_email_config_is_still_valid() -> None:
    s = make()
    assert s.emails_enabled is False


def test_complete_email_config_is_valid() -> None:
    s = make(
        SMTP_HOST="smtp.example.com",
        EMAILS_FROM_EMAIL="info@example.com",
        SMTP_USER="mailer",
        SMTP_PASSWORD="mailer-pw",
    )
    assert s.emails_enabled is True


def test_host_without_from_email_fails() -> None:
    assert_rejected(["EMAILS_FROM_EMAIL"], SMTP_HOST="smtp.example.com")


def test_user_without_password_fails() -> None:
    assert_rejected(
        ["SMTP_PASSWORD"],
        SMTP_HOST="smtp.example.com",
        EMAILS_FROM_EMAIL="info@example.com",
        SMTP_USER="mailer",
    )


def test_password_without_user_fails() -> None:
    assert_rejected(
        ["SMTP_USER"],
        SMTP_HOST="smtp.example.com",
        EMAILS_FROM_EMAIL="info@example.com",
        SMTP_PASSWORD="mailer-pw",
    )


def test_tls_and_ssl_together_fail() -> None:
    assert_rejected(["SMTP_TLS", "SMTP_SSL"], SMTP_TLS=True, SMTP_SSL=True)


def test_ssl_alone_is_valid() -> None:
    assert make(SMTP_TLS=False, SMTP_SSL=True).SMTP_SSL is True


@pytest.mark.parametrize("port", [0, -1, 65536, 70000])
def test_port_out_of_range_fails(port: int) -> None:
    assert_rejected(["SMTP_PORT"], SMTP_PORT=port)


@pytest.mark.parametrize("port", [1, 25, 65535])
def test_port_in_range_is_valid(port: int) -> None:
    assert make(SMTP_PORT=port).SMTP_PORT == port


def test_one_error_lists_every_offending_variable() -> None:
    assert_rejected(
        ["EMAILS_FROM_EMAIL", "SMTP_PASSWORD", "SMTP_SSL", "SMTP_PORT"],
        SMTP_HOST="smtp.example.com",
        SMTP_USER="mailer",
        SMTP_TLS=True,
        SMTP_SSL=True,
        SMTP_PORT=0,
    )
