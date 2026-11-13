import re
from datetime import datetime, timedelta
from typing import List, Optional
from src.models import ClassSession, CalendarEvent, DiffType, DiffResult

CATALAN_WEEKDAYS = {
    0: "Dilluns",
    1: "Dimarts",
    2: "Dimecres",
    3: "Dijous",
    4: "Divendres",
    5: "Dissabte",
    6: "Diumenge"
}


def _format_datetime(dt: datetime) -> str:
    weekday = CATALAN_WEEKDAYS.get(dt.weekday(), "")
    return f"{weekday} {dt.strftime('%d/%m %H:%M')}"


def _normalize_name(name: str) -> str:
    # Retirar etiquetes prèvies de cancel·lació
    cleaned = re.sub(r"^\[\s*CANCEL[·\.]?LA[TD][A]?\s*\]\s*", "", name, flags=re.IGNORECASE)
    # Retirar claudàtors i parèntesis (ex: [Pràctiques], (Teoria))
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    # Retirar codis inicials d'assignatura (ex: '23974 - ', '23974: ')
    cleaned = re.sub(r"^\s*\d+\s*[-–—:]\s*", "", cleaned)
    # Conservar caràcters alfanumèrics i caràcters catalans/castellans
    cleaned = re.sub(r"[^a-zA-Z0-9àèéíòóúçñÀÈÉÍÒÓÚÇÑ]", "", cleaned)
    return cleaned.lower().strip()


def _extract_activity_type(text: str) -> Optional[str]:
    """Extreu la tipologia (teoria, seminaris, pràctiques) d'un text."""
    lower = text.lower()
    if any(k in lower for k in ["pràcti", "practi", "laboratori", "lab"]):
        return "practica"
    if any(k in lower for k in ["seminari", "seminar", "sem"]):
        return "seminari"
    if any(k in lower for k in ["teoria", "teo"]):
        return "teoria"
    return None


def _normalize_room(room: Optional[str]) -> str:
    if not room:
        return "sense aula"
    cleaned = room.strip().lower()
    cleaned = re.sub(r"[\.\s]+$", "", cleaned)
    placeholders = [
        "sense aula",
        "sense aules",
        "sense aula assignada",
        "sense aules assignades",
        "sin aula",
        "sin aulas",
        "sin aula asignada",
        "sin aulas asignadas",
        "pendent",
        "pendent d'assignar",
        "pendent assignar",
        "no assignada",
        "por determinar",
        "a determinar",
        "no classroom"
    ]
    if any(cleaned == p or cleaned.startswith(p) for p in placeholders):
        return "sense aula"
    cleaned = re.sub(r"^aula\s*", "", cleaned)
    return cleaned.strip()


def _sessions_match(web: ClassSession, cal: CalendarEvent, tolerance_minutes: int = 15) -> bool:
    norm_web = _normalize_name(web.subject_name)
    norm_cal = _normalize_name(cal.summary)

    name_match = (norm_web == norm_cal) or (norm_web in norm_cal) or (norm_cal in norm_web)
    if not name_match:
        return False

    time_diff = abs(web.start_time - cal.start_time)
    return time_diff <= timedelta(minutes=tolerance_minutes)


def compare_schedules(
    web_sessions: List[ClassSession],
    calendar_events: List[CalendarEvent]
) -> List[DiffResult]:
    diffs: List[DiffResult] = []
    matched_calendar_ids = set()
    matched_web_indices = set()

    # Step 1: Match web sessions against calendar events with exact or near time match (<= 15 min)
    for idx, web in enumerate(web_sessions):
        match: Optional[CalendarEvent] = None
        for cal in calendar_events:
            if cal.event_id in matched_calendar_ids:
                continue
            if _sessions_match(web, cal):
                match = cal
                break

        if match:
            matched_web_indices.add(idx)
            matched_calendar_ids.add(match.event_id)

            web_room = web.classroom.strip()
            cal_room = (match.location or "").strip()
            was_cancelled = bool(re.search(r"^\[\s*CANCEL[·\.]?LA[TD][A]?\s*\]", match.summary, re.IGNORECASE))

            if was_cancelled:
                diffs.append(
                    DiffResult(
                        diff_type=DiffType.RESTORED,
                        subject_name=web.subject_name,
                        web_session=web,
                        calendar_event=match,
                        old_value=match.summary,
                        new_value=web.subject_name,
                        message=f"Classe reactivada/confirmada: {web.subject_name} ({_format_datetime(web.start_time)} - {web.end_time.strftime('%H:%M')})"
                    )
                )
            elif _normalize_room(web_room) != _normalize_room(cal_room):
                diffs.append(
                    DiffResult(
                        diff_type=DiffType.ROOM_CHANGE,
                        subject_name=web.subject_name,
                        web_session=web,
                        calendar_event=match,
                        old_value=cal_room or "Sense aula",
                        new_value=web_room,
                        message=f"Canvi d'aula a {web.subject_name} ({_format_datetime(web.start_time)}): {cal_room or 'Sense aula'} ➔ {web_room}"
                    )
                )
            else:
                diffs.append(
                    DiffResult(
                        diff_type=DiffType.UNCHANGED,
                        subject_name=web.subject_name,
                        web_session=web,
                        calendar_event=match,
                        message=f"Sense canvis: {web.subject_name} ({_format_datetime(web.start_time)})"
                    )
                )

    # Step 2: Match unmatched sessions for rescheduling (TIME_CHANGE / canvi de dia o d'hora a la setmana)
    unmatched_web_indices = [i for i in range(len(web_sessions)) if i not in matched_web_indices]
    for idx in unmatched_web_indices:
        web = web_sessions[idx]
        norm_web = _normalize_name(web.subject_name)
        web_type = _extract_activity_type(f"{web.session_type or ''} {web.subject_name}")

        best_match: Optional[CalendarEvent] = None
        best_score = -1

        for cal in calendar_events:
            if cal.event_id in matched_calendar_ids:
                continue

            norm_cal = _normalize_name(cal.summary)
            name_match = (norm_web == norm_cal) or (norm_web in norm_cal) or (norm_cal in norm_web)
            if not name_match:
                continue

            cal_type = _extract_activity_type(f"{cal.summary} {cal.description or ''}")

            if web_type and cal_type:
                if web_type == cal_type:
                    score = 10
                else:
                    continue  # Diferents tipologies de la mateixa assignatura no s'han de creuar
            elif not web_type and not cal_type:
                score = 5
            else:
                score = 3

            if score > best_score:
                best_score = score
                best_match = cal

        if best_match:
            matched_web_indices.add(idx)
            matched_calendar_ids.add(best_match.event_id)

            old_time_str = f"{_format_datetime(best_match.start_time)} - {best_match.end_time.strftime('%H:%M')}"
            new_time_str = f"{_format_datetime(web.start_time)} - {web.end_time.strftime('%H:%M')}"
            room_info = f" (Aula: {web.classroom})" if web.classroom and web.classroom != "Sense aula" else ""

            diffs.append(
                DiffResult(
                    diff_type=DiffType.TIME_CHANGE,
                    subject_name=web.subject_name,
                    web_session=web,
                    calendar_event=best_match,
                    old_value=old_time_str,
                    new_value=new_time_str,
                    message=f"Canvi de dia/horari a {web.subject_name}: de {old_time_str} a {new_time_str}{room_info}"
                )
            )

    # Step 3: Any remaining unmatched web sessions are truly new sessions
    for idx, web in enumerate(web_sessions):
        if idx not in matched_web_indices:
            new_time_str = f"{_format_datetime(web.start_time)} - {web.end_time.strftime('%H:%M')}"
            diffs.append(
                DiffResult(
                    diff_type=DiffType.NEW_SESSION,
                    subject_name=web.subject_name,
                    web_session=web,
                    new_value=web.classroom,
                    message=f"Nova classe: {web.subject_name} ({new_time_str}) a {web.classroom}"
                )
            )

    # Step 4: Any remaining unmatched calendar events are cancelled
    for cal in calendar_events:
        if cal.event_id not in matched_calendar_ids:
            if cal.summary.startswith("[CANCEL·LADA]"):
                continue
            cal_time_str = f"{_format_datetime(cal.start_time)} - {cal.end_time.strftime('%H:%M')}"
            diffs.append(
                DiffResult(
                    diff_type=DiffType.CANCELLED,
                    subject_name=cal.summary,
                    calendar_event=cal,
                    message=f"Classe cancel·lada o no programada: {cal.summary} ({cal_time_str})"
                )
            )

    return diffs
