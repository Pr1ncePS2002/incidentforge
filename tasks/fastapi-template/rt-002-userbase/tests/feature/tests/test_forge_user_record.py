"""Round-trip guarantees for exported user records (app.user_record)."""

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.user_record import (
    UserRecordError,
    load_user_record,
    save_user_record,
    update_user_record,
)

BASE_RECORD: dict[str, Any] = {
    "email": "Round.Trip@Example.com",
    "is_active": True,
    "is_superuser": False,
    "full_name": None,
    "id": "0b5c3f0e-8d55-4a8e-9a39-3f1f6f0f2a11",
    "team": "ops",
    "login_count": 0,
    "preferences": {
        "theme": "dark",
        "page_size": 25,
        "ratio": 0.5,
        "tags": ["a", "b"],
        "beta": False,
    },
}


def base() -> dict[str, Any]:
    return copy.deepcopy(BASE_RECORD)


def write_raw(path: Path, record: dict[str, Any]) -> None:
    # compact form, deliberately different from the writer's own formatting
    path.write_text(json.dumps(record), encoding="utf-8")


def read_raw(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def only_file(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir())


def _boom(*_args: Any, **_kwargs: Any) -> None:
    raise OSError("simulated disk failure")


# ---- normal behaviour ------------------------------------------------------


def test_error_type_is_value_error() -> None:
    assert issubclass(UserRecordError, ValueError)


def test_roundtrip_without_change_is_identical(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    loaded = load_user_record(path)
    assert loaded == BASE_RECORD
    save_user_record(path, loaded)
    again = read_raw(path)
    assert again == BASE_RECORD
    assert list(again) == list(BASE_RECORD)
    assert load_user_record(str(path)) == BASE_RECORD


def test_saving_unchanged_record_does_not_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "user.json"
    save_user_record(path, base())
    before = path.read_bytes()
    monkeypatch.setattr(os, "replace", _boom)
    save_user_record(path, load_user_record(path))
    assert path.read_bytes() == before
    assert only_file(tmp_path) == ["user.json"]


def test_save_creates_new_file(tmp_path: Path) -> None:
    path = tmp_path / "new.json"
    save_user_record(path, base())
    assert load_user_record(path) == BASE_RECORD
    assert only_file(tmp_path) == ["new.json"]


def test_changing_one_field_changes_only_that_field(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    returned = update_user_record(path, {"full_name": "Ada Lovelace"})
    expected = base()
    expected["full_name"] = "Ada Lovelace"
    on_disk = read_raw(path)
    assert on_disk == expected
    assert returned == expected
    assert list(on_disk) == list(BASE_RECORD)


def test_email_is_stored_verbatim(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    update_user_record(path, {"team": "dev"})
    assert read_raw(path)["email"] == "Round.Trip@Example.com"


def test_invalid_files_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(UserRecordError):
        load_user_record(path)
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(UserRecordError):
        load_user_record(path)
    bad = base()
    bad["is_active"] = "yes"
    write_raw(path, bad)
    with pytest.raises(UserRecordError):
        load_user_record(path)
    bad = base()
    bad["email"] = "not-an-email"
    write_raw(path, bad)
    with pytest.raises(UserRecordError):
        load_user_record(path)


# ---- injected faults -------------------------------------------------------


def test_fault_dropped_field_unknown_keys_survive_update(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    update_user_record(path, {"is_active": False})
    on_disk = read_raw(path)
    assert on_disk["is_active"] is False
    for key in ("id", "team", "login_count", "preferences"):
        assert on_disk[key] == BASE_RECORD[key]


def test_fault_dropped_field_unset_fields_stay_unset(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    record = {"email": "sparse@example.com", "team": "ops"}
    write_raw(path, record)
    update_user_record(path, {"email": "sparse2@example.com"})
    on_disk = read_raw(path)
    assert on_disk == {"email": "sparse2@example.com", "team": "ops"}
    assert "is_superuser" not in on_disk
    assert "full_name" not in on_disk
    assert "is_active" not in on_disk


def test_fault_default_overwrite_explicit_defaults_kept(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    update_user_record(path, {"team": "dev"})
    on_disk = read_raw(path)
    assert "full_name" in on_disk and on_disk["full_name"] is None
    assert on_disk["is_superuser"] is False
    assert on_disk["is_active"] is True
    assert on_disk["login_count"] == 0
    assert on_disk["preferences"]["beta"] is False


def test_fault_default_overwrite_explicit_empty_kept(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    update_user_record(path, {"full_name": ""})
    on_disk = read_raw(path)
    assert on_disk["full_name"] == ""
    update_user_record(path, {"team": ""})
    on_disk = read_raw(path)
    assert on_disk["full_name"] == ""
    assert on_disk["team"] == ""
    assert load_user_record(path)["full_name"] == ""


def test_fault_type_drift_values_keep_types(tmp_path: Path) -> None:
    path = tmp_path / "user.json"
    write_raw(path, base())
    update_user_record(path, {"is_superuser": True})
    on_disk = read_raw(path)
    prefs = on_disk["preferences"]
    assert type(prefs["page_size"]) is int
    assert type(prefs["ratio"]) is float
    assert type(prefs["tags"]) is list and prefs["tags"] == ["a", "b"]
    assert type(prefs["beta"]) is bool
    assert type(on_disk["login_count"]) is int
    assert on_disk["is_superuser"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"is_active": "false"},
        {"is_superuser": 1},
        {"full_name": 42},
        {"email": 12345},
    ],
)
def test_fault_type_drift_coerced_user_fields_rejected(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    path = tmp_path / "user.json"
    save_user_record(path, base())
    before = path.read_bytes()
    with pytest.raises(UserRecordError):
        update_user_record(path, changes)
    assert path.read_bytes() == before
    assert only_file(tmp_path) == ["user.json"]


@pytest.mark.parametrize(
    "changes",
    [
        {"tags": ("a", "b")},
        {"roles": {"admin", "ops"}},
        {"seen_at": datetime(2024, 1, 1, tzinfo=timezone.utc)},
        {"preferences": {"ratio": float("nan")}},
        {"preferences": {1: "numeric key"}},
    ],
)
def test_fault_type_drift_non_json_values_rejected(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    path = tmp_path / "user.json"
    save_user_record(path, base())
    before = path.read_bytes()
    with pytest.raises(UserRecordError):
        update_user_record(path, changes)
    assert path.read_bytes() == before
    assert only_file(tmp_path) == ["user.json"]


def test_fault_partial_write_replace_fails_keeps_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "user.json"
    save_user_record(path, base())
    before = path.read_bytes()
    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        update_user_record(path, {"full_name": "Half Written"})
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert only_file(tmp_path) == ["user.json"]
    assert load_user_record(path) == BASE_RECORD


def test_fault_partial_write_fsync_fails_keeps_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "user.json"
    save_user_record(path, base())
    before = path.read_bytes()
    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(OSError):
        update_user_record(path, {"team": "x" * 10000})
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert only_file(tmp_path) == ["user.json"]


def test_fault_partial_write_invalid_record_never_touches_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "user.json"
    save_user_record(path, base())
    before = path.read_bytes()
    bad = base()
    bad["full_name"] = "x" * 256
    with pytest.raises(UserRecordError):
        save_user_record(path, bad)
    assert path.read_bytes() == before
    assert only_file(tmp_path) == ["user.json"]
