"""lossless read-modify-write of UserCreate draft files."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.models import UserCreate
from app.user_drafts import edit_user_draft

BASE_RECORD: dict[str, Any] = {
    "email": "draft.user@example.com",
    "password": "draft-pass-1234",
    "full_name": None,
    "is_superuser": False,
    "team": "growth",
    "quota": 5,
    "ratio": 1.5,
    "tags": ["beta"],
    "meta": {"source": "import", "retries": 0},
    "notify": True,
}


def write_draft(tmp_path: Path, record: dict[str, Any]) -> Path:
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(record, indent=4), encoding="utf-8")
    return path


def read_draft(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_noop_edit_leaves_file_identical(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    before = path.read_bytes()
    user = edit_user_draft(path)
    assert isinstance(user, UserCreate)
    assert path.read_bytes() == before
    edit_user_draft(str(path), {})
    assert path.read_bytes() == before


def test_edit_with_same_values_leaves_file_identical(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    before = path.read_bytes()
    edit_user_draft(path, {"is_superuser": False, "team": "growth"})
    assert path.read_bytes() == before


def test_changing_one_field_changes_only_that_field(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    user = edit_user_draft(path, {"full_name": "Draft User"})
    assert user.full_name == "Draft User"
    assert read_draft(path) == {**BASE_RECORD, "full_name": "Draft User"}


def test_returns_validated_user(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    user = edit_user_draft(path, {"is_superuser": True})
    assert user.email == "draft.user@example.com"
    assert user.is_superuser is True
    assert read_draft(path)["is_superuser"] is True


def test_new_key_in_changes_is_added(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    edit_user_draft(path, {"region": "south"})
    assert read_draft(path) == {**BASE_RECORD, "region": "south"}


def test_non_object_draft_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "draft.json"
    path.write_text(json.dumps([BASE_RECORD]), encoding="utf-8")
    with pytest.raises(ValueError):
        edit_user_draft(path, {"full_name": "x"})


def test_fault_dropped_field_unknown_keys_survive(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    edit_user_draft(path, {"email": "renamed@example.com"})
    after = read_draft(path)
    for key in ("team", "quota", "ratio", "tags", "meta", "notify"):
        assert key in after, f"{key} was dropped"
        assert after[key] == BASE_RECORD[key]
    assert after["email"] == "renamed@example.com"


def test_fault_dropped_field_untouched_known_fields_survive(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    edit_user_draft(path, {"team": "core"})
    after = read_draft(path)
    assert after["password"] == BASE_RECORD["password"]
    assert after["email"] == BASE_RECORD["email"]
    assert after["team"] == "core"


def test_fault_default_overwrite_unset_stays_unset(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    assert "is_active" not in BASE_RECORD
    edit_user_draft(path, {"full_name": "Draft User"})
    after = read_draft(path)
    assert "is_active" not in after


def test_fault_default_overwrite_explicit_default_kept(tmp_path: Path) -> None:
    record = {**BASE_RECORD, "is_active": True}
    path = write_draft(tmp_path, record)
    edit_user_draft(path, {"team": "core"})
    after = read_draft(path)
    assert "is_superuser" in after and after["is_superuser"] is False
    assert "is_active" in after and after["is_active"] is True


def test_fault_default_overwrite_explicit_null_kept(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    edit_user_draft(path, {"email": "other@example.com"})
    after = read_draft(path)
    assert "full_name" in after
    assert after["full_name"] is None


def test_fault_default_overwrite_explicit_empty_kept(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    edit_user_draft(path, {"full_name": ""})
    after = read_draft(path)
    assert after["full_name"] == ""
    edit_user_draft(path, {"team": "core"})
    assert read_draft(path)["full_name"] == ""


def test_fault_type_drift_untouched_values_keep_type(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    edit_user_draft(path, {"full_name": "Draft User"})
    after = read_draft(path)
    assert type(after["quota"]) is int and after["quota"] == 5
    assert type(after["ratio"]) is float and after["ratio"] == 1.5
    assert after["tags"] == ["beta"]
    assert after["meta"] == {"source": "import", "retries": 0}
    assert type(after["meta"]["retries"]) is int
    assert after["notify"] is True
    assert after["is_superuser"] is False


def test_fault_type_drift_changed_field_uses_field_type(tmp_path: Path) -> None:
    record = {**BASE_RECORD, "is_active": True}
    path = write_draft(tmp_path, record)
    user = edit_user_draft(path, {"is_active": "false"})
    assert user.is_active is False
    after = read_draft(path)
    assert after["is_active"] is False


def test_fault_partial_write_invalid_change_keeps_previous(tmp_path: Path) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        edit_user_draft(path, {"password": "short", "team": "core"})
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        edit_user_draft(path, {"email": "not-an-email"})
    assert path.read_bytes() == before


def test_fault_partial_write_failed_replace_keeps_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_draft(tmp_path, BASE_RECORD)
    before = path.read_bytes()

    def broken_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        edit_user_draft(path, {"full_name": "Draft User"})
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["draft.json"]
