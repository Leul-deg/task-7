"""
Unit tests for application configuration classes.

Covers:
  - ProductionConfig._validate() raises RuntimeError when SECRET_KEY is unset
  - ProductionConfig._validate() passes silently when SECRET_KEY is set
  - Config defaults (dev/test) are not production-safe
"""
import os
import pytest

from app.config import ProductionConfig, TestingConfig, DevelopmentConfig


class TestProductionConfigValidation:
    def test_raises_when_secret_key_missing(self, monkeypatch):
        """_validate() raises RuntimeError when SECRET_KEY env var is absent."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            ProductionConfig._validate()

    def test_passes_when_secret_key_set(self, monkeypatch):
        """_validate() returns without error when SECRET_KEY is present."""
        monkeypatch.setenv("SECRET_KEY", "a-very-secure-production-key-abc123")
        # Should not raise
        ProductionConfig._validate()

    def test_empty_string_secret_key_raises(self, monkeypatch):
        """An empty string SECRET_KEY is falsy and must also trigger the error."""
        monkeypatch.setenv("SECRET_KEY", "")
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            ProductionConfig._validate()


class TestConfigDefaults:
    def test_testing_config_uses_in_memory_sqlite(self):
        """TestingConfig uses an in-memory database."""
        assert ":memory:" in TestingConfig.SQLALCHEMY_DATABASE_URI

    def test_testing_config_disables_csrf(self):
        """TestingConfig disables CSRF for test client convenience."""
        assert TestingConfig.WTF_CSRF_ENABLED is False

    def test_production_config_sets_secure_cookie(self):
        """ProductionConfig sets SESSION_COOKIE_SECURE."""
        assert ProductionConfig.SESSION_COOKIE_SECURE is True

    def test_production_config_disables_debug(self):
        """ProductionConfig must not run with DEBUG enabled."""
        assert ProductionConfig.DEBUG is False
