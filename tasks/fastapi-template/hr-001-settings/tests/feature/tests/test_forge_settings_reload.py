"""runtime reload of Settings: new values apply without restart, bad reloads are rejected."""

import pytest

from app.core import config
from app.core.config import Settings

BASE: dict[str, object] = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
DEFAULT_EXPIRE = 60 * 24 * 8
ENV_VARS = (
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_TLS",
    "SMTP_SSL",
    "EMAILS_FROM_EMAIL",
    "EMAILS_FROM_NAME",
    "FRONTEND_HOST",
    "SENTRY_DSN",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def raw(**overrides: object) -> dict[str, object]:
    return {**BASE, **overrides}


# unchanged behaviour


def test_settings_without_reload_are_unchanged() -> None:
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_EXPIRE
    assert s.SMTP_PORT == 587
    assert s.SMTP_HOST is None
    assert s.EMAILS_FROM_NAME == "forge"
    assert s.emails_enabled is False


def test_shared_settings_instance_supports_reload() -> None:
    assert callable(getattr(config.settings, "reload", None))


def test_reload_applies_on_next_read() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=5)
    result = s.reload(raw(ACCESS_TOKEN_EXPIRE_MINUTES="15"))
    assert result is s
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    s.reload(raw(ACCESS_TOKEN_EXPIRE_MINUTES="20"))
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 20


# stale-capture


class TokenIssuer:
    """a consumer that keeps the settings object it was constructed with."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def expiry_minutes(self) -> int:
        return self.settings.ACCESS_TOKEN_EXPIRE_MINUTES


def test_fault_stale_capture_held_reference_sees_new_value() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=5)
    issuer = TokenIssuer(s)
    imported_alias = s
    assert issuer.expiry_minutes() == 5

    s.reload(raw(ACCESS_TOKEN_EXPIRE_MINUTES="15"))

    assert issuer.expiry_minutes() == 15
    assert imported_alias.ACCESS_TOKEN_EXPIRE_MINUTES == 15


def test_fault_stale_capture_reload_keeps_identity() -> None:
    s = make(SMTP_PORT=2525)
    before_id = id(s)
    returned = s.reload(raw(SMTP_PORT="2626"))
    assert returned is s
    assert id(s) == before_id
    assert s.SMTP_PORT == 2626


# invalid-reload


def test_fault_invalid_reload_bad_port_keeps_last_good() -> None:
    s = make(SMTP_PORT=2525, ACCESS_TOKEN_EXPIRE_MINUTES=5)
    with pytest.raises(ValueError) as exc:
        s.reload(raw(SMTP_PORT="not-a-port", ACCESS_TOKEN_EXPIRE_MINUTES="30"))
    assert "SMTP_PORT" in str(exc.value)
    assert s.SMTP_PORT == 2525
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 5

    s.reload(raw(SMTP_PORT="2626"))
    assert s.SMTP_PORT == 2626


def test_fault_invalid_reload_missing_required_key() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=5)
    values = raw(ACCESS_TOKEN_EXPIRE_MINUTES="30")
    del values["SECRET_KEY"]
    with pytest.raises(ValueError) as exc:
        s.reload(values)
    assert "SECRET_KEY" in str(exc.value)
    assert s.SECRET_KEY == "forge-secret-key-for-tests"
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 5


def test_fault_invalid_reload_bad_email() -> None:
    s = make(SMTP_HOST="smtp.example.com", EMAILS_FROM_EMAIL="info@example.com")
    with pytest.raises(ValueError) as exc:
        s.reload(raw(SMTP_HOST="smtp2.example.com", EMAILS_FROM_EMAIL="not-an-email"))
    assert "EMAILS_FROM_EMAIL" in str(exc.value)
    assert s.SMTP_HOST == "smtp.example.com"
    assert s.EMAILS_FROM_EMAIL == "info@example.com"
    assert s.emails_enabled is True


# partial-reload


def test_fault_partial_reload_rejected_pair_stays_old() -> None:
    s = make(SMTP_USER="mailer-a", SMTP_PASSWORD="pw-a")
    with pytest.raises(ValueError):
        s.reload(raw(SMTP_USER="mailer-b", SMTP_PASSWORD="pw-b", SMTP_PORT="bad"))
    assert (s.SMTP_USER, s.SMTP_PASSWORD) == ("mailer-a", "pw-a")


def test_fault_partial_reload_related_values_swap_together() -> None:
    s = make(
        SMTP_HOST="smtp-a.example.com",
        EMAILS_FROM_EMAIL="a@example.com",
        SMTP_USER="mailer-a",
        SMTP_PASSWORD="pw-a",
    )
    s.reload(
        raw(
            SMTP_HOST="smtp-b.example.com",
            EMAILS_FROM_EMAIL="b@example.com",
            SMTP_USER="mailer-b",
            SMTP_PASSWORD="pw-b",
        )
    )
    assert (s.SMTP_HOST, s.EMAILS_FROM_EMAIL, s.SMTP_USER, s.SMTP_PASSWORD) == (
        "smtp-b.example.com",
        "b@example.com",
        "mailer-b",
        "pw-b",
    )


def test_fault_partial_reload_derived_value_follows_source() -> None:
    s = make()
    assert s.EMAILS_FROM_NAME == "forge"
    s.reload(raw(PROJECT_NAME="forge-two"))
    assert s.PROJECT_NAME == "forge-two"
    assert s.EMAILS_FROM_NAME == "forge-two"


def test_fault_partial_reload_computed_flag_follows() -> None:
    s = make()
    assert s.emails_enabled is False
    s.reload(raw(SMTP_HOST="smtp.example.com", EMAILS_FROM_EMAIL="info@example.com"))
    assert s.emails_enabled is True


# reload-unset


def test_fault_reload_unset_falls_back_to_default() -> None:
    s = make(
        ACCESS_TOKEN_EXPIRE_MINUTES=5,
        SMTP_HOST="smtp.example.com",
        EMAILS_FROM_EMAIL="info@example.com",
        SMTP_PORT=2525,
    )
    s.reload(raw())
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_EXPIRE
    assert s.SMTP_HOST is None
    assert s.EMAILS_FROM_EMAIL is None
    assert s.SMTP_PORT == 587
    assert s.emails_enabled is False


def test_fault_reload_unset_ignores_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "7")
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=5)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 5
    s.reload(raw())
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_EXPIRE
