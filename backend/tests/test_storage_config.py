import pytest
from storage.config import StorageConfigError, StorageSettings, load_storage_settings
from storage.pool import Storage
from storage_fixtures import RUNTIME, SETTINGS, CANARY


@pytest.mark.parametrize(
    "key,value",
    [
        ("APP_STORAGE_ENABLED", "yes"),
        ("APP_DB_POOL_SIZE", "0"),
        ("APP_DB_POOL_SIZE", "1000"),
        ("APP_DB_MAX_WAITING", "0"),
        ("APP_DB_WAIT_SECONDS", "nan"),
        ("APP_DB_WAIT_SECONDS", "99"),
    ],
)
def test_invalid_storage_settings_are_safe(key, value):
    with pytest.raises(StorageConfigError) as caught:
        load_storage_settings({key: value, "APP_DATABASE_URL": CANARY})
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize(
    "dsn",
    [
        RUNTIME.replace("127.0.0.1", "company.example.test"),
        RUNTIME.replace("aqua_app?", "financial?"),
        RUNTIME.replace("aqua_app_runtime", "postgres"),
        RUNTIME + "&options=-csearch_path%3Dpublic",
        RUNTIME + "&service=company",
        RUNTIME.replace("5432", "9000"),
        "postgresql://private-secret@bad-host",
    ],
)
def test_runtime_configuration_cannot_select_analytical_or_admin_connection(dsn):
    with pytest.raises(StorageConfigError):
        StorageSettings(True, dsn)


def test_disabled_storage_does_not_use_analytical_url():
    config = load_storage_settings({"DATABASE_URL": CANARY})
    assert not config.enabled and config.dsn == ""
    assert Storage(config).readiness()["application_storage"] == "disabled"
    assert "fixture-only" not in repr(SETTINGS)
