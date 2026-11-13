import logging
from datetime import date, timedelta
from typing import List
import httpx

from src.models import DiffResult, DiffType
from src.config import get_settings

logger = logging.getLogger(__name__)


def format_alert_message(diffs: List[DiffResult], target_date: date) -> str:
    """
    Construeix un missatge estructurat en format HTML per a Telegram
    amb els canvis detectats per a la setmana de la data objectiu.
    """
    actionable_diffs = [d for d in diffs if d.diff_type != DiffType.UNCHANGED]
    if not actionable_diffs:
        return ""

    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)
    week_str = f"Setmana del {monday.strftime('%d/%m')} al {sunday.strftime('%d/%m/%Y')}"
    lines = [f"🚨 <b>ALERTA D'HORARI UPF ({week_str})</b>\n"]

    time_changes = [d for d in actionable_diffs if d.diff_type == DiffType.TIME_CHANGE]
    room_changes = [d for d in actionable_diffs if d.diff_type == DiffType.ROOM_CHANGE]
    cancellations = [d for d in actionable_diffs if d.diff_type == DiffType.CANCELLED]
    new_sessions = [d for d in actionable_diffs if d.diff_type == DiffType.NEW_SESSION]
    restored = [d for d in actionable_diffs if d.diff_type == DiffType.RESTORED]

    if time_changes:
        lines.append("🕒 <b>Canvis de dia / horari:</b>")
        for d in time_changes:
            lines.append(f"• {d.message}")
        lines.append("")

    if room_changes:
        lines.append("⚠️ <b>Canvis d'aula:</b>")
        for d in room_changes:
            lines.append(f"• <b>{d.subject_name}</b>: {d.old_value} ➔ <code>{d.new_value}</code>")
        lines.append("")

    if cancellations:
        lines.append("❌ <b>Classes cancel·lades:</b>")
        for d in cancellations:
            lines.append(f"• {d.message}")
        lines.append("")

    if new_sessions:
        lines.append("➕ <b>Noves classes programades:</b>")
        for d in new_sessions:
            lines.append(f"• {d.message}")
        lines.append("")

    if restored:
        lines.append("✅ <b>Classes confirmades / reactivades:</b>")
        for d in restored:
            lines.append(f"• {d.message}")
        lines.append("")

    lines.append("ℹ️ <i>Google Calendar s'ha actualitzat automàticament.</i>")
    return "\n".join(lines)


def send_telegram_alert(message: str) -> bool:
    """
    Envia un missatge al xat de Telegram configurat via Bot API oficial.
    """
    if not message.strip():
        return True

    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Credencials de Telegram no configurades. No s'ha enviat cap alerta.")
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Notificació Telegram enviada amb èxit.")
            return True
    except Exception as exc:
        logger.error(f"Error enviant notificació Telegram: {exc}")
        return False
