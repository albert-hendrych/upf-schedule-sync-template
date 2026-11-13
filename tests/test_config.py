import pytest
from src.config import Settings, get_settings

def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("UNI_USERNAME", "u123456")
    monkeypatch.setenv("UNI_PASSWORD", "secret123")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_KEY", '{"type": "service_account"}')
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "test@group.calendar.google.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    monkeypatch.setenv("SUBJECT_GROUP_FILTERS", "23962:S201,P201")
    
    # Clear lru_cache for testing
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.UNI_USERNAME == "u123456"
    assert settings.UNI_PASSWORD == "secret123"
    assert settings.GOOGLE_CALENDAR_ID == "test@group.calendar.google.com"
    assert settings.TELEGRAM_BOT_TOKEN == "123456:ABC-DEF"
    assert settings.TELEGRAM_CHAT_ID == "987654321"
    assert settings.TIMEZONE == "Europe/Madrid"
    assert settings.SUBJECT_GROUP_FILTERS == "23962:S201,P201"
    get_settings.cache_clear()
