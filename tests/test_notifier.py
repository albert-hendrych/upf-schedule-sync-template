from datetime import date
import respx
import httpx
from src.models import DiffResult, DiffType
from src.notifier import format_alert_message, send_telegram_alert


def test_format_alert_message():
    diffs = [
        DiffResult(
            diff_type=DiffType.ROOM_CHANGE,
            subject_name="Sistemes Operatius",
            old_value="Aula 52.217",
            new_value="Aula 13.002",
            message="Canvi d'aula a Sistemes Operatius: Aula 52.217 ➔ Aula 13.002"
        ),
        DiffResult(
            diff_type=DiffType.CANCELLED,
            subject_name="Xarxes",
            message="Classe cancel·lada: Xarxes"
        ),
        DiffResult(
            diff_type=DiffType.RESTORED,
            subject_name="Simulació de Xarxes",
            message="Classe reactivada/confirmada: Simulació de Xarxes (08:30 - 10:30)"
        )
    ]
    msg = format_alert_message(diffs, date(2026, 10, 8))
    assert "Setmana del 05/10 al 11/10/2026" in msg
    assert "Canvis d'aula" in msg
    assert "Aula 13.002" in msg
    assert "cancel·lades" in msg.lower()
    assert "confirmades" in msg.lower() or "reactivades" in msg.lower()


def test_format_alert_message_with_time_change():
    diffs = [
        DiffResult(
            diff_type=DiffType.TIME_CHANGE,
            subject_name="Simulació de Xarxes",
            old_value="Dijous 22/10 08:30 - 10:30",
            new_value="Dimecres 21/10 10:30 - 12:30",
            message="Canvi de dia/horari a Simulació de Xarxes: de Dijous 22/10 08:30 a Dimecres 21/10 10:30 (Aula: 52.321)"
        )
    ]
    msg = format_alert_message(diffs, date(2026, 10, 22))
    assert "Setmana del 19/10 al 25/10/2026" in msg
    assert "Canvis de dia / horari" in msg
    assert "Dijous 22/10" in msg
    assert "Dimecres 21/10" in msg


def test_format_alert_message_empty_when_unchanged():
    diffs = [
        DiffResult(
            diff_type=DiffType.UNCHANGED,
            subject_name="Matemàtiques",
            message="Sense canvis"
        )
    ]
    msg = format_alert_message(diffs, date(2026, 10, 8))
    assert msg == ""


@respx.mock
def test_send_telegram_alert_success(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    from src.config import get_settings
    get_settings.cache_clear()

    route = respx.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(200, json={"ok": True})
    success = send_telegram_alert("Missatge de prova")
    assert success is True
    assert route.called
