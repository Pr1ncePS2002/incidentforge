"""Round-trip guarantees for the settings dotenv writer."""

import json
import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.env_file import read_env_file, update_env_file

REQUIRED = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}

ORIGINAL = (
    "# deployment settings\n"
    "DOMAIN=localhost\n"
    "\n"
    "export ENVIRONMENT=local\n"
    "PROJECT_NAME='Full Stack Project'\n"
    'EMAILS_FROM_NAME="Ops # Team"\n'
    "SMTP_HOST=smtp.example.com  # relay\n"
    "SMTP_PORT=587\n"
    "SMTP_TLS=true\n"
    "SENTRY_DSN=\n"
    "CUSTOM_UNKNOWN_FLAG=keep-me\r\n"
    "TRAILING=last"
)

EXPECTED = {
    "DOMAIN": "localhost",
    "ENVIRONMENT": "local",
    "PROJECT_NAME": "Full Stack Project",
    "EMAILS_FROM_NAME": "Ops # Team",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_TLS": "true",
    "SENTRY_DSN": "",
    "CUSTOM_UNKNOWN_FLAG": "keep-me",
    "TRAILING": "last",
}


@pytest.fixture
def env_path(tmp_path: Path) -> Path:
    directory = tmp_path / "cfg"
    directory.mkdir()
    path = directory / ".env"
    path.write_bytes(ORIGINAL.encode("utf-8"))
    return path


def _boom(*_args: object, **_kwargs: object) -> None:
    raise OSError("disk full")


def test_read_reports_every_assignment(env_path: Path) -> None:
    assert read_env_file(env_path) == EXPECTED


def test_read_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_env_file(tmp_path / "absent.env") == {}


def test_noop_save_keeps_file_identical(env_path: Path) -> None:
    update_env_file(env_path, {})
    assert env_path.read_bytes() == ORIGINAL.encode("utf-8")
    update_env_file(env_path, read_env_file(env_path))
    assert env_path.read_bytes() == ORIGINAL.encode("utf-8")


def test_noop_save_does_not_rewrite(
    env_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "replace", _boom)
    update_env_file(env_path, read_env_file(env_path))
    update_env_file(env_path, {"SMTP_PORT": 587, "SMTP_TLS": True})
    assert env_path.read_bytes() == ORIGINAL.encode("utf-8")


def test_fault_dropped_field_only_changed_line_differs(env_path: Path) -> None:
    update_env_file(env_path, {"SMTP_HOST": "mail.internal"})
    assert read_env_file(env_path) == {**EXPECTED, "SMTP_HOST": "mail.internal"}
    before = ORIGINAL.split("\n")
    after = env_path.read_bytes().decode("utf-8").split("\n")
    assert len(before) == len(after)
    diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(diffs) == 1
    assert after[diffs[0]].startswith("SMTP_HOST=")
    assert "CUSTOM_UNKNOWN_FLAG=keep-me\r" in after
    assert after[-1] == "TRAILING=last"


def test_fault_dropped_field_new_key_appended(env_path: Path) -> None:
    update_env_file(env_path, {"SMTP_USER": "mailer"})
    text = env_path.read_bytes().decode("utf-8")
    assert text.startswith(ORIGINAL)
    assert read_env_file(env_path) == {**EXPECTED, "SMTP_USER": "mailer"}


def test_fault_default_overwrite_explicit_default_and_empty_kept(
    env_path: Path,
) -> None:
    update_env_file(
        env_path,
        {
            "SMTP_PORT": 587,
            "ACCESS_TOKEN_EXPIRE_MINUTES": 60 * 24 * 8,
            "EMAILS_FROM_NAME": "",
            "SMTP_SSL": False,
            "EMAIL_RESET_TOKEN_EXPIRE_HOURS": 0,
        },
    )
    values = read_env_file(env_path)
    assert values["SMTP_PORT"] == "587"
    assert values["ACCESS_TOKEN_EXPIRE_MINUTES"] == "11520"
    assert "EMAILS_FROM_NAME" in values and values["EMAILS_FROM_NAME"] == ""
    assert values["SMTP_SSL"] == "false"
    assert values["EMAIL_RESET_TOKEN_EXPIRE_HOURS"] == "0"
    assert "SENTRY_DSN" in values and values["SENTRY_DSN"] == ""
    assert "SMTP_PORT=587\n" in env_path.read_bytes().decode("utf-8")


def test_unset_removes_key_but_empty_is_kept(env_path: Path) -> None:
    update_env_file(env_path, {"SMTP_HOST": None, "SENTRY_DSN": ""})
    values = read_env_file(env_path)
    assert "SMTP_HOST" not in values
    assert values["SENTRY_DSN"] == ""
    expected = {k: v for k, v in EXPECTED.items() if k != "SMTP_HOST"}
    assert values == expected


def test_fault_type_drift_values_reload_with_their_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "fresh.env"
    tricky = "O'Brien \\ \"ops\" #1"
    update_env_file(
        path,
        {
            "SMTP_PORT": 2525,
            "SMTP_TLS": False,
            "SMTP_SSL": True,
            "ACCESS_TOKEN_EXPIRE_MINUTES": 90,
            "EMAILS_FROM_NAME": tricky,
        },
    )
    raw = read_env_file(path)
    assert raw["SMTP_PORT"] == "2525"
    assert raw["SMTP_TLS"] == "false"
    assert raw["SMTP_SSL"] == "true"
    assert raw["ACCESS_TOKEN_EXPIRE_MINUTES"] == "90"
    assert raw["EMAILS_FROM_NAME"] == tricky

    for name in (
        "SMTP_PORT",
        "SMTP_TLS",
        "SMTP_SSL",
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "EMAILS_FROM_NAME",
        "EMAILS_FROM_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=path, **REQUIRED)  # type: ignore[arg-type]
    assert isinstance(s.SMTP_PORT, int) and s.SMTP_PORT == 2525
    assert s.SMTP_TLS is False
    assert s.SMTP_SSL is True
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 90
    assert s.EMAILS_FROM_NAME == tricky


def test_fault_type_drift_list_stays_list(env_path: Path) -> None:
    origins = ["http://localhost", "https://example.com"]
    update_env_file(env_path, {"BACKEND_CORS_ORIGINS": origins})
    assert json.loads(read_env_file(env_path)["BACKEND_CORS_ORIGINS"]) == origins


def test_fault_partial_write_bad_value_keeps_previous_file(env_path: Path) -> None:
    with pytest.raises(TypeError):
        update_env_file(env_path, {"SMTP_HOST": "new.host", "BROKEN": object()})
    assert env_path.read_bytes() == ORIGINAL.encode("utf-8")
    assert sorted(os.listdir(env_path.parent)) == [".env"]


def test_fault_partial_write_failed_replace_keeps_previous_file(
    env_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        update_env_file(env_path, {"SMTP_HOST": "new.host", "SMTP_PORT": 25})
    assert env_path.read_bytes() == ORIGINAL.encode("utf-8")
    assert sorted(os.listdir(env_path.parent)) == [".env"]


def test_invalid_key_rejected(env_path: Path) -> None:
    with pytest.raises(ValueError):
        update_env_file(env_path, {"BAD KEY": "x"})
    assert env_path.read_bytes() == ORIGINAL.encode("utf-8")


def test_missing_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "new.env"
    update_env_file(path, {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": 465})
    assert read_env_file(path) == {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "465"}
