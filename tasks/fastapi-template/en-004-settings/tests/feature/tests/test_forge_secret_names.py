"""environment-scoped secret store paths built from Settings.DEPLOYMENT_ENVIRONMENT."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEPLOYMENT_ENVIRONMENT", raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_default_environment_is_local_and_stable() -> None:
    s = make()
    assert s.DEPLOYMENT_ENVIRONMENT == "local"
    assert s.secret_name("smtp-password") == "local/smtp-password"


@pytest.mark.parametrize("env", ["local", "staging", "production"])
def test_allowed_environments_load(env: str) -> None:
    s = make(DEPLOYMENT_ENVIRONMENT=env)
    assert s.secret_name("db-password") == f"{env}/db-password"


def test_fault_unscoped_key_environments_do_not_collide() -> None:
    staging = make(DEPLOYMENT_ENVIRONMENT="staging").secret_name("db-password")
    production = make(DEPLOYMENT_ENVIRONMENT="production").secret_name("db-password")
    assert staging != production
    assert staging == "staging/db-password"
    assert production == "production/db-password"


def test_fault_wrong_env_source_uses_configured_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "production")
    s = make()
    assert s.DEPLOYMENT_ENVIRONMENT == "production"
    assert s.secret_name("gateway-credentials") == "production/gateway-credentials"


def test_fault_wrong_env_source_not_default_local() -> None:
    s = make(DEPLOYMENT_ENVIRONMENT="staging")
    name = s.secret_name("gateway-credentials")
    assert not name.startswith("local/")
    assert name == "staging/gateway-credentials"


@pytest.mark.parametrize(
    "env", ["", "prod", "Production", "dev", " staging", "staging/production"]
)
def test_fault_unknown_env_rejected_at_startup(env: str) -> None:
    with pytest.raises(ValueError) as exc:
        make(DEPLOYMENT_ENVIRONMENT=env)
    assert "DEPLOYMENT_ENVIRONMENT" in str(exc.value)


@pytest.mark.parametrize("env", ["", "qa"])
def test_fault_unknown_env_rejected_when_building_name(env: str) -> None:
    s = make(DEPLOYMENT_ENVIRONMENT="production")
    with pytest.raises(ValueError) as exc:
        s.DEPLOYMENT_ENVIRONMENT = env
        s.secret_name("db-password")
    assert "DEPLOYMENT_ENVIRONMENT" in str(exc.value)


@pytest.mark.parametrize("name", ["db/password", "/db", "db/", "production/db"])
def test_fault_separator_injection_in_name(name: str) -> None:
    s = make(DEPLOYMENT_ENVIRONMENT="staging")
    with pytest.raises(ValueError):
        s.secret_name(name)


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_secret_name_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        make().secret_name(name)
