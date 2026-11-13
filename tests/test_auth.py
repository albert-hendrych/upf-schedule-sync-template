import pytest
from unittest.mock import patch, MagicMock
from src.auth import AuthenticationError, login_and_get_cookies


def test_authentication_error_raised():
    err = AuthenticationError("Credencials no vàlides")
    assert "Credencials no vàlides" in str(err)


def test_login_missing_credentials(monkeypatch):
    monkeypatch.setenv("UNI_USERNAME", "")
    monkeypatch.setenv("UNI_PASSWORD", "")
    from src.config import get_settings
    get_settings.cache_clear()
    
    with pytest.raises(AuthenticationError, match="UNI_USERNAME o UNI_PASSWORD no estan configurats"):
        login_and_get_cookies()


@patch("src.auth.sync_playwright")
def test_login_success_mock(mock_playwright, monkeypatch, tmp_path):
    monkeypatch.setenv("UNI_USERNAME", "u123456")
    monkeypatch.setenv("UNI_PASSWORD", "pwd123")
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    from src.config import get_settings
    get_settings.cache_clear()

    # Setup mock playwright
    mock_p = MagicMock()
    mock_playwright.return_value.__enter__.return_value = mock_p
    mock_browser = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_page = MagicMock()
    mock_context.new_page.return_value = mock_page

    # Return valid cookies
    mock_context.cookies.return_value = [
        {"name": "JSESSIONID", "value": "mock_cookie_123"},
        {"name": "CAMPUS_SESSION", "value": "abc"}
    ]
    # Configure mock locator
    mock_el = MagicMock()
    mock_el.is_visible.return_value = False
    mock_el.inner_text.return_value = ""
    mock_page.locator.return_value.first = mock_el

    cookies = login_and_get_cookies()
    assert cookies["JSESSIONID"] == "mock_cookie_123"
    assert mock_browser.close.called


@patch("src.auth.sync_playwright")
def test_login_with_target_date_handles_coverage_and_globals(mock_playwright, monkeypatch, tmp_path):
    from datetime import date
    from src import auth
    monkeypatch.setenv("UNI_USERNAME", "u123456")
    monkeypatch.setenv("UNI_PASSWORD", "pwd123")
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    from src.config import get_settings
    get_settings.cache_clear()

    mock_p = MagicMock()
    mock_playwright.return_value.__enter__.return_value = mock_p
    mock_browser = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_page = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_context.pages = [mock_page]

    mock_context.cookies.return_value = [
        {"name": "JSESSIONID", "value": "mock_cookie_123"},
    ]
    mock_el = MagicMock()
    mock_el.is_visible.return_value = False
    mock_el.inner_text.return_value = ""
    mock_page.locator.return_value.first = mock_el

    # Set mock intercepted sessions and epochs
    auth._INTERCEPTED_SESSIONS.append({"title": "Test Class", "start": "2026-10-26 08:30:00", "end": "2026-10-26 10:30:00"})
    auth._INTERCEPTED_START_EPOCH = 1792972800
    auth._INTERCEPTED_END_EPOCH = 1793577600
    auth._INTERCEPTED_ENDPOINT_URL = "https://matricula.upf.edu/pds/control/[Ajax]selecionarRangoHorarios"

    cookies = login_and_get_cookies(target_date=date(2026, 10, 26))
    assert cookies["JSESSIONID"] == "mock_cookie_123"
    assert mock_browser.close.called
    auth.clear_intercepted_sessions()

