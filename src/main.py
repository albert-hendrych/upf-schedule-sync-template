import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.config import get_settings
from src.auth import login_and_get_cookies, AuthenticationError
from src.scraper import fetch_schedule
from src.calendar_manager import CalendarManager
from src.diff_engine import compare_schedules
from src.models import DiffType
from src.notifier import format_alert_message, send_telegram_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("schedule_sync")


def get_default_target_date(tz_name: str) -> date:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    # Si és cap de setmana (dissabte o diumenge), auditem la setmana vinent
    if now.weekday() == 5:  # Dissabte
        return now.date() + timedelta(days=2)
    elif now.weekday() == 6:  # Diumenge
        return now.date() + timedelta(days=1)
    # De dilluns a divendres, auditem la setmana actual
    return now.date()


def run_pipeline(target_date: Optional[date] = None, dry_run: bool = False) -> int:
    settings = get_settings()
    if target_date is None:
        target_date = get_default_target_date(settings.TIMEZONE)

    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)

    logger.info("=" * 60)
    logger.info(f"Iniciant sincronització i auditoria d'horaris per a la setmana del {monday} al {sunday}...")
    logger.info(f"Mode dry-run: {dry_run}")
    logger.info("=" * 60)

    try:
        # Step 1: Headless login
        logger.info("Pas 1/5: Autenticació a la UPF...")
        cookies = login_and_get_cookies(target_date)

        # Step 2: Extract official schedule
        logger.info(f"Pas 2/5: Extracció de l'horari oficial de la setmana ({monday} a {sunday})...")
        web_sessions = fetch_schedule(cookies, target_date)
        logger.info(f"S'han trobat {len(web_sessions)} sessions oficials a la graella de la UPF.")

        # Step 3: Fetch Google Calendar events
        logger.info("Pas 3/5: Consulta d'esdeveniments existents a Google Calendar per a la setmana...")
        cal_manager = CalendarManager()
        cal_events = cal_manager.get_events_for_week(target_date)
        logger.info(f"S'han trobat {len(cal_events)} esdeveniments al calendari de Google.")

        # Step 4: Compare
        logger.info("Pas 4/5: Comparant fonts de dades i calculant discrepàncies...")
        diffs = compare_schedules(web_sessions, cal_events)

        actionable = [d for d in diffs if d.diff_type != DiffType.UNCHANGED]
        logger.info(f"Total discrepàncies detectades: {len(actionable)}")

        for d in actionable:
            logger.info(f"  [{d.diff_type.value}] {d.message}")

        # Step 5: Apply changes and notify
        if actionable:
            if not dry_run:
                logger.info("Pas 5/5: Aplicant canvis a Google Calendar i enviant alertes...")
                for d in actionable:
                    if d.diff_type == DiffType.ROOM_CHANGE and d.calendar_event and d.web_session:
                        cal_manager.update_event_classroom(d.calendar_event.event_id, d.web_session.classroom)
                    elif d.diff_type == DiffType.TIME_CHANGE and d.calendar_event and d.web_session:
                        cal_manager.update_event_time_and_classroom(
                            event_id=d.calendar_event.event_id,
                            new_start=d.web_session.start_time,
                            new_end=d.web_session.end_time,
                            new_classroom=d.web_session.classroom,
                            current_summary=d.calendar_event.summary
                        )
                    elif d.diff_type == DiffType.NEW_SESSION and d.web_session:
                        cal_manager.create_event(d.web_session)
                    elif d.diff_type == DiffType.CANCELLED and d.calendar_event:
                        cal_manager.mark_event_cancelled(d.calendar_event.event_id, d.calendar_event.summary)
                    elif d.diff_type == DiffType.RESTORED and d.calendar_event:
                        cal_manager.restore_event(d.calendar_event.event_id, d.calendar_event.summary)

                alert_text = format_alert_message(diffs, target_date)
                send_telegram_alert(alert_text)
            else:
                logger.info("Mode dry-run activat: No s'ha modificat Google Calendar ni s'ha enviat cap alerta.")
        else:
            logger.info("Pas 5/5: No s'ha detectat cap canvi. El calendari està completament actualitzat.")

        logger.info("Procés finalitzat correctament!")
        return 0

    except AuthenticationError as auth_err:
        logger.critical(f"Error crític d'autenticació: {auth_err}")
        return 1
    except Exception as exc:
        logger.critical(f"Error inesperat durant l'execució: {exc}", exc_info=True)
        return 1


def main():
    parser = argparse.ArgumentParser(description="UPF Schedule Synchronizer and Auditor")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Data o dia de la setmana a auditar en format YYYY-MM-DD (per defecte la setmana actual o vinent)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa la comprovació sense escriure a Google Calendar ni enviar alertes"
    )
    args = parser.parse_args()

    parsed_date = None
    if args.date:
        try:
            parsed_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("Format de data no vàlid. Utilitza YYYY-MM-DD.")
            sys.exit(1)

    exit_code = run_pipeline(target_date=parsed_date, dry_run=args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
