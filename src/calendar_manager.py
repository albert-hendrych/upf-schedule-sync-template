import base64
import json
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
import dateutil.parser

from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.models import CalendarEvent, ClassSession
from src.config import get_settings
from src.diff_engine import _normalize_name

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarManager:
    def __init__(self, service=None, calendar_id: Optional[str] = None):
        settings = get_settings()
        self.calendar_id = calendar_id or settings.GOOGLE_CALENDAR_ID
        self.timezone = settings.TIMEZONE
        self._color_cache: Dict[str, str] = {}

        if service:
            self.service = service
        else:
            self.service = self._init_service(settings.GOOGLE_SERVICE_ACCOUNT_KEY)

    def _init_service(self, sa_key_str: str):
        if not sa_key_str:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY no està definit.")

        raw = sa_key_str.strip()
        if raw.startswith("{"):
            info = json.loads(raw)
        else:
            try:
                decoded = base64.b64decode(raw).decode("utf-8")
                info = json.loads(decoded)
            except Exception:
                info = json.loads(raw)

        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        return build("calendar", "v3", credentials=credentials)

    def get_events_for_date_range(self, start_date: date, end_date: date) -> List[CalendarEvent]:
        tz = ZoneInfo(self.timezone)
        time_min = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=tz).isoformat()
        time_max = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=tz).isoformat()

        logger.info(f"Obtenint esdeveniments de Google Calendar entre {time_min} i {time_max}...")
        res = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        items = res.get("items", [])
        events: List[CalendarEvent] = []

        for it in items:
            start_raw = it.get("start", {}).get("dateTime") or it.get("start", {}).get("date")
            end_raw = it.get("end", {}).get("dateTime") or it.get("end", {}).get("date")
            if not start_raw or not end_raw:
                continue

            start_dt = dateutil.parser.isoparse(start_raw)
            end_dt = dateutil.parser.isoparse(end_raw)

            raw_color = it.get("colorId")
            color_id = str(raw_color) if isinstance(raw_color, str) and raw_color else None
            summary = it.get("summary", "")
            if color_id and summary:
                norm_sub = _normalize_name(summary)
                if norm_sub:
                    self._color_cache[norm_sub] = color_id

            events.append(
                CalendarEvent(
                    event_id=it["id"],
                    summary=summary,
                    start_time=start_dt,
                    end_time=end_dt,
                    location=it.get("location"),
                    description=it.get("description"),
                    color_id=color_id
                )
            )

        return events

    def get_events_for_date(self, target_date: date) -> List[CalendarEvent]:
        return self.get_events_for_date_range(target_date, target_date)

    def get_events_for_week(self, target_date: date) -> List[CalendarEvent]:
        monday = target_date - timedelta(days=target_date.weekday())
        sunday = monday + timedelta(days=6)
        return self.get_events_for_date_range(monday, sunday)

    def get_color_for_subject(self, subject_name: str) -> Optional[str]:
        norm = _normalize_name(subject_name)
        if not norm:
            return None

        # 1. Comprovar la memòria cau
        if norm in self._color_cache:
            return self._color_cache[norm]

        # Comprovar si alguna clau de la memòria cau és un subconjunt o conté norm
        for cached_norm, cid in self._color_cache.items():
            if (cached_norm == norm) or (cached_norm in norm) or (norm in cached_norm):
                return cid

        # 2. Cercar a l'API de Google Calendar esdeveniments existents de la mateixa assignatura
        try:
            res = self.service.events().list(
                calendarId=self.calendar_id,
                q=subject_name,
                singleEvents=True,
                maxResults=25
            ).execute()
            items = res.get("items", []) if isinstance(res, dict) else []
            for it in items:
                if not isinstance(it, dict):
                    continue
                cid = it.get("colorId")
                summary = it.get("summary", "")
                norm_cal = _normalize_name(summary)
                if isinstance(cid, str) and cid and norm_cal and ((norm_cal == norm) or (norm_cal in norm) or (norm in norm_cal)):
                    self._color_cache[norm] = cid
                    return cid

            # Si no s'ha trobat amb 'q=subject_name', buscar en una finestra temporal al voltant d'avui
            now = datetime.now()
            t_min = (now - timedelta(days=60)).isoformat() + "Z"
            t_max = (now + timedelta(days=60)).isoformat() + "Z"
            res_recent = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=t_min,
                timeMax=t_max,
                singleEvents=True,
                maxResults=100
            ).execute()
            items_recent = res_recent.get("items", []) if isinstance(res_recent, dict) else []
            for it in items_recent:
                if not isinstance(it, dict):
                    continue
                cid = it.get("colorId")
                summary = it.get("summary", "")
                norm_cal = _normalize_name(summary)
                if isinstance(cid, str) and cid and norm_cal and ((norm_cal == norm) or (norm_cal in norm) or (norm in norm_cal)):
                    self._color_cache[norm] = cid
                    return cid

        except Exception as err:
            logger.warning(f"No s'ha pogut obtenir el color per a l'assignatura '{subject_name}': {err}")

        return None

    def create_event(self, session: ClassSession) -> str:
        summary = session.subject_name
        if session.session_type:
            summary += f" [{session.session_type}]"

        description_lines = [
            f"Assignatura: {session.subject_name}",
            f"Aula: {session.classroom}",
        ]
        if session.group_id:
            description_lines.append(f"Grup: {session.group_id}")
        if session.teachers:
            description_lines.append(f"Professorat: {', '.join(session.teachers)}")
        if session.notes:
            description_lines.append(f"Observacions: {session.notes}")
        description_lines.append("[UPF-AUTOSYNC]")

        body = {
            "summary": summary,
            "location": session.classroom,
            "description": "\n".join(description_lines),
            "start": {"dateTime": session.start_time.isoformat()},
            "end": {"dateTime": session.end_time.isoformat()},
            "visibility": "public"
        }

        color_id = self.get_color_for_subject(session.subject_name)
        if color_id:
            body["colorId"] = color_id

        created = self.service.events().insert(
            calendarId=self.calendar_id,
            body=body
        ).execute()
        logger.info(
            f"Esdeveniment creat a Google Calendar: {summary} ({created.get('id')}) amb visibilitat pública"
            + (f" i color {color_id}" if color_id else "")
        )
        return created["id"]

    def update_event_classroom(self, event_id: str, new_classroom: str) -> None:
        patch_body = {"location": new_classroom}
        self.service.events().patch(
            calendarId=self.calendar_id,
            eventId=event_id,
            body=patch_body
        ).execute()
        logger.info(f"Esdeveniment {event_id} actualitzat amb nova aula: {new_classroom}")

    def mark_event_cancelled(self, event_id: str, current_summary: str) -> None:
        new_summary = (
            f"[CANCEL·LADA] {current_summary}"
            if not current_summary.startswith("[CANCEL·LADA]")
            else current_summary
        )
        patch_body = {"summary": new_summary}
        self.service.events().patch(
            calendarId=self.calendar_id,
            eventId=event_id,
            body=patch_body
        ).execute()
        logger.info(f"Esdeveniment {event_id} marcat com a cancel·lat: {new_summary}")

    def restore_event(self, event_id: str, current_summary: str) -> None:
        import re
        new_summary = re.sub(r"^\[\s*CANCEL[·\.]?LA[TD][A]?\s*\]\s*", "", current_summary, flags=re.IGNORECASE).strip()
        patch_body = {"summary": new_summary}
        self.service.events().patch(
            calendarId=self.calendar_id,
            eventId=event_id,
            body=patch_body
        ).execute()
        logger.info(f"Esdeveniment {event_id} restaurat (retirada etiqueta de cancel·lació): {new_summary}")

    def update_event_time_and_classroom(
        self,
        event_id: str,
        new_start: datetime,
        new_end: datetime,
        new_classroom: Optional[str] = None,
        current_summary: Optional[str] = None
    ) -> None:
        patch_body = {
            "start": {"dateTime": new_start.isoformat()},
            "end": {"dateTime": new_end.isoformat()}
        }
        if new_classroom:
            patch_body["location"] = new_classroom

        if current_summary:
            import re
            cleaned_summary = re.sub(
                r"^\[\s*CANCEL[·\.]?LA[TD][A]?\s*\]\s*", "", current_summary, flags=re.IGNORECASE
            ).strip()
            if cleaned_summary != current_summary:
                patch_body["summary"] = cleaned_summary

        self.service.events().patch(
            calendarId=self.calendar_id,
            eventId=event_id,
            body=patch_body
        ).execute()
        logger.info(
            f"Esdeveniment {event_id} mogut/actualitzat d'horari: nou inici={new_start}, nou final={new_end}"
            + (f", aula={new_classroom}" if new_classroom else "")
        )

