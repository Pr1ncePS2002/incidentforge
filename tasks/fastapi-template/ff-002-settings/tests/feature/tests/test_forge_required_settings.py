"""fault cases for blank or placeholder core settings; each must fail at startup."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
CHECKED = ("PROJECT_NAME", "SECRET_KEY", "FIRST_SUPERUSER_PASSWORD")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CHECKED:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_valid_config_still_loads() -> None:
    s = make()
    assert s.PROJECT_NAME == "forge"
    assert s.SECRET_KEY == "forge-secret-key-for-tests"
    assert s.FIRST_SUPERUSER_PASSWORD == "forge-superuser-pw"


@pytest.mark.parametrize("value", ["todo-app", "my-todo-secret-123", "xxx-yyy", "a<b>c"])
def test_values_merely_containing_placeholder_words_load(value: str) -> None:
    assert make(PROJECT_NAME=value).PROJECT_NAME == value
    assert make(SECRET_KEY=value).SECRET_KEY == value


@pytest.mark.parametrize("name", CHECKED)
def test_fault_empty_string(name: str) -> None:
    assert_rejected([name], **{name: ""})


@pytest.mark.parametrize("name", CHECKED)
@pytest.mark.parametrize("value", [" ", "   ", "\t\n"])
def test_fault_empty_whitespace_only(name: str, value: str) -> None:
    assert_rejected([name], **{name: value})


@pytest.mark.parametrize("name", CHECKED)
@pytest.mark.parametrize(
    "value",
    ["todo", "TODO", "  tbd  ", "FixMe", "changeme", "replace-me", "replaceme", "xxx", "<fill-me>", "<your-secret-here>"],
)
def test_fault_placeholder(name: str, value: str) -> None:
    assert_rejected([name], **{name: value})


def test_fault_several_bad_all_named() -> None:
    assert_rejected(
        list(CHECKED),
        PROJECT_NAME="<project-name>",
        SECRET_KEY="   ",
        FIRST_SUPERUSER_PASSWORD="todo",
    )


def test_fault_several_bad_two_of_three() -> None:
    with pytest.raises(ValueError) as exc:
        make(SECRET_KEY="", FIRST_SUPERUSER_PASSWORD="<fill-me>")
    msg = str(exc.value)
    assert "SECRET_KEY" in msg
    assert "FIRST_SUPERUSER_PASSWORD" in msg
