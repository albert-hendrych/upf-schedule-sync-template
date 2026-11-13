import html
import json
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import dateutil.parser
import httpx

from src.config import get_settings
from src.models import ClassSession
from src.auth import get_intercepted_sessions, get_intercepted_metadata

logger = logging.getLogger(__name__)


def _normalize_filter_key(value: str) -> str:
    norm = unicodedata.normalize("NFKD", value).encode("ASCII", "ignore").decode("utf-8").lower()
    return re.sub(r"[^a-z0-9]", "", norm)


def parse_subject_group_filters(raw_filters: Optional[str]) -> Dict[str, List[str]]:
    """
    Analitza la variable d'entorn SUBJECT_GROUP_FILTERS.
    Accepta:
      - Format compacte: '23962:S201,P201;Comunicació Tècnica en Anglès:201'
      - Format JSON: '{"23962": ["S201", "P201"]}'
    Retorna un diccionari {clau_normalitzada: [GRUPS_EN_MAJÚSCULES]}.
    """
    if not raw_filters or not raw_filters.strip():
        return {}

    stripped = raw_filters.strip()
    parsed: Dict[str, List[str]] = {}

    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                for raw_key, raw_groups in data.items():
                    key = _normalize_filter_key(str(raw_key))
                    if not key:
                        continue
                    if isinstance(raw_groups, str):
                        tokens = [g.strip().upper() for g in raw_groups.split(",") if g.strip()]
                    elif isinstance(raw_groups, list):
                        tokens = [str(g).strip().upper() for g in raw_groups if str(g).strip()]
                    else:
                        continue
                    if tokens:
                        parsed[key] = tokens
                return parsed
        except json.JSONDecodeError as err:
            logger.warning(f"SUBJECT_GROUP_FILTERS té un JSON invàlid i s'ignorarà ({err}).")
            return {}

    for entry in re.split(r"[;\n]+", stripped):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            logger.warning(f"Entrada de SUBJECT_GROUP_FILTERS sense ':' ignorada: '{entry}'")
            continue
        raw_key, raw_groups = entry.split(":", 1)
        key = _normalize_filter_key(raw_key)
        tokens = [g.strip().upper() for g in raw_groups.split(",") if g.strip()]
        if key and tokens:
            parsed.setdefault(key, []).extend(tokens)

    return parsed


def is_session_relevant(
    session: ClassSession,
    group_filters: Optional[Dict[str, List[str]]] = None
) -> bool:
    """
    Filtra sessions de seminaris/pràctiques segons SUBJECT_GROUP_FILTERS.
    A la UPF, algunes assignatures mostren tots els grups de seminari/pràctica
    de tots els estudiants al calendari. Si s'ha configurat un filtre per a
    l'assignatura (per codi o per nom), només es conserven els grups indicats.
    Les sessions de Teoria i la resta d'assignatures es mantenen sempre.
    """
    if group_filters is None:
        group_filters = parse_subject_group_filters(get_settings().SUBJECT_GROUP_FILTERS)

    if not group_filters:
        return True

    raw_code = _normalize_filter_key(str(session.raw_id or ""))
    clean_title = _normalize_filter_key(session.subject_name)

    matched_allowed_groups: List[str] = []
    for filter_key, allowed_groups in group_filters.items():
        code_match = bool(raw_code and raw_code == filter_key)
        title_match = bool(
            filter_key
            and (not filter_key.isdigit() or len(filter_key) >= 4)
            and filter_key in clean_title
        )
        if code_match or title_match:
            matched_allowed_groups.extend(allowed_groups)

    if not matched_allowed_groups:
        return True

    type_norm = f"{(session.session_type or '')} {session.subject_name}".lower()
    group_str = (session.group_id or "").strip().upper()

    is_seminar = (
        any(w in type_norm for w in ["seminari", "seminar", "sem"])
        or group_str.startswith("S")
    )
    is_practice = (
        any(w in type_norm for w in ["pràcti", "practi", "laboratori", "lab", "pra"])
        or group_str.startswith("P")
    )

    if is_seminar or is_practice:
        notes_str = (session.notes or "").upper()
        if any(tok in group_str or tok in notes_str for tok in matched_allowed_groups):
            return True
        logger.info(
            f"Sessió de '{session.subject_name}' descartada: grup '{session.group_id}' "
            f"no coincideix amb el filtre configurat ({', '.join(matched_allowed_groups)})."
        )
        return False

    return True


def deduplicate_sessions(sessions: List[ClassSession]) -> List[ClassSession]:
    """Elimina sessions duplicades mantenint l'ordre original."""
    seen = set()
    unique: List[ClassSession] = []
    for s in sessions:
        key = (s.subject_name, s.start_time, s.end_time, s.classroom)
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def is_placeholder_classroom(classroom: Optional[str]) -> bool:
    """Comprova si el valor de l'aula és un marcador genèric com 'Sense aules assignades'."""
    if not classroom:
        return True
    cleaned = classroom.strip().lower()
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
        "no asignada",
        "por determinar",
        "a determinar",
        "no classroom"
    ]
    return any(cleaned == p or cleaned.startswith(p) for p in placeholders)


def extract_classroom_from_notes(notes: Optional[str]) -> Optional[str]:
    """
    Extreu el nom d'una aula a partir del text d'observacions o comentaris.
    Ex: 'Aula 52.019. Grups S101, S102, S103 i S104 junts a la mateixa aula.' ➔ 'Aula 52.019'
        'Laboratori 54.004' ➔ 'Laboratori 54.004'
        'A la 52.019' ➔ 'Aula 52.019'
    """
    if not notes or not isinstance(notes, str):
        return None

    cleaned_notes = html.unescape(notes).strip()
    cleaned_notes = re.sub(r"<[^>]+>", " ", cleaned_notes)

    # 1. Cerca 'Aula / Laboratori / Lab / Auditori' seguit de codi tipus '52.019' o '52.S01'
    m1 = re.search(
        r"\b(Aula|Laboratori|Lab|Auditori)\s*[:\-]?\s*([0-9]{2}\.[0-9A-Za-z]{3,4})\b",
        cleaned_notes,
        re.IGNORECASE
    )
    if m1:
        prefix = m1.group(1).capitalize()
        if prefix.lower() == "lab":
            prefix = "Laboratori"
        return f"{prefix} {m1.group(2)}"

    # 2. Cerca 'Aula Magna' o 'Auditori'
    m2 = re.search(r"\b(Aula\s+Magna|Auditori)\b", cleaned_notes, re.IGNORECASE)
    if m2:
        return m2.group(1).title()

    # 3. Cerca patró típic d'aula UPF XX.YYY (ex: '52.019', '13.002', '52.S01')
    m3 = re.search(r"\b([0-9]{2}\.[0-9]{3}[A-Za-z]?|[0-9]{2}\.[A-Za-z][0-9]{2})\b", cleaned_notes)
    if m3:
        return f"Aula {m3.group(1)}"

    # 4. Cerca 'Aula' seguida d'identificador
    m4 = re.search(r"\b(Aula\s+[A-Za-z0-9\-]+)\b", cleaned_notes, re.IGNORECASE)
    if m4:
        candidate = m4.group(1).strip()
        if not any(k in candidate.lower() for k in ["virtual", "global", "assignad", "sense", "sin"]):
            return candidate

    return None


def parse_raw_sessions(
    data: List[Dict[str, Any]],
    tz_name: str = "Europe/Madrid",
    group_filters: Optional[Dict[str, List[str]]] = None
) -> List[ClassSession]:
    sessions: List[ClassSession] = []
    tz = ZoneInfo(tz_name)
    resolved_filters = (
        group_filters
        if group_filters is not None
        else parse_subject_group_filters(get_settings().SUBJECT_GROUP_FILTERS)
    )

    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("festivoNoLectivo") is True:
            continue
        if "title" not in item or "start" not in item or "end" not in item:
            continue

        raw_title = item.get("title", "")
        clean_title = html.unescape(raw_title).strip()

        classroom_raw = item.get("aula", "")
        classroom = html.unescape(classroom_raw).strip() if classroom_raw else "Sense aula"

        raw_notes = item.get("observacion") or item.get("comentario") or item.get("observaciones") or item.get("observacions")
        clean_notes = html.unescape(raw_notes).strip() if raw_notes and isinstance(raw_notes, str) else None

        # Si l'aula és un marcador de posició com 'Sense aules assignades', mirem si podem extreure-la de les observacions
        if is_placeholder_classroom(classroom):
            extracted = extract_classroom_from_notes(clean_notes)
            if extracted:
                logger.info(f"Aula recuperada de les observacions per a '{clean_title}': '{classroom}' ➔ '{extracted}'")
                classroom = extracted
            else:
                classroom = "Sense aula"

        try:
            raw_start = str(item["start"]).strip()
            raw_end = str(item["end"]).strip()
            try:
                start_dt = datetime.strptime(raw_start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            except ValueError:
                start_dt = dateutil.parser.parse(raw_start)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=tz)
                else:
                    start_dt = start_dt.astimezone(tz)

            try:
                end_dt = datetime.strptime(raw_end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            except ValueError:
                end_dt = dateutil.parser.parse(raw_end)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=tz)
                else:
                    end_dt = end_dt.astimezone(tz)
        except Exception as err:
            logger.warning(f"Error parsing session datetime ({item.get('start')}, {item.get('end')}): {err}")
            continue

        raw_teachers = item.get("profesores", [])
        teachers = [html.unescape(t).strip() for t in raw_teachers if isinstance(t, str)]

        group_val = item.get("grup") or item.get("grupo")
        type_val = item.get("tipologia") or item.get("tipo")

        session = ClassSession(
            subject_name=clean_title,
            start_time=start_dt,
            end_time=end_dt,
            classroom=classroom,
            group_id=str(group_val).strip() if group_val else None,
            raw_id=str(item.get("codAsignatura")).strip() if item.get("codAsignatura") else None,
            session_type=html.unescape(type_val).strip() if type_val else None,
            teachers=teachers,
            notes=clean_notes
        )

        if is_session_relevant(session, resolved_filters):
            sessions.append(session)

    return sessions


def fetch_schedule(cookies: Dict[str, str], target_date: date) -> List[ClassSession]:
    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE)

    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)

    start_dt = datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=tz)
    end_dt = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=tz)

    start_epoch = int(start_dt.timestamp())
    end_epoch = int(end_dt.timestamp())

    # 1. Comprovar si tenim sessions ja interceptades que COBREIXIN realment el rang complet de la setmana
    meta = get_intercepted_metadata()
    intercepted_raw = get_intercepted_sessions()

    meta_start = meta.get("start_epoch")
    meta_end = meta.get("end_epoch")
    meta_start_date = datetime.fromtimestamp(meta_start, tz).date() if meta_start is not None else None

    is_range_covered = (
        meta_start is not None
        and meta_end is not None
        and meta_start_date is not None
        and meta_start_date <= monday
        and meta_end >= end_epoch
    )

    if intercepted_raw and is_range_covered:
        logger.info(f"Processant {len(intercepted_raw)} sessions interceptades que cobreixen la setmana {monday} a {sunday}...")
        cached_sessions = parse_raw_sessions(intercepted_raw, settings.TIMEZONE)
        matched = [s for s in cached_sessions if monday <= s.start_time.date() <= sunday]
        unique_matched = deduplicate_sessions(matched)
        unique_matched.sort(key=lambda s: s.start_time)
        logger.info(f"S'han trobat {len(unique_matched)} sessions per a la setmana {monday} a {sunday} a la graella interceptada del navegador.")
        return unique_matched

    # 2. Consultar el rang complet de la setmana oficial a FullCalendar (dilluns 00:00:00 a diumenge 23:59:59)
    # Utilitzem l'endpoint detectat pel navegador (matricula.upf.edu o secretariavirtual.upf.edu)
    base_endpoint = meta.get("endpoint_url")
    if base_endpoint:
        url = f"{base_endpoint}?rnd=4236.0&start={start_epoch}&end={end_epoch}"
        referer = f"{base_endpoint.rsplit('/', 1)[0]}/PubliHoraAlumCalendario?rnd=176.0"
    else:
        url = settings.SECRETARIA_AJAX_URL.format(start=start_epoch, end=end_epoch)
        referer = "https://secretariavirtual.upf.edu/pds/control/PubliHoraAlumCalendario?rnd=176.0"

    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json; charset=utf-8",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    logger.info(f"Querying UPF schedule for week {monday} to {sunday} ({start_epoch} to {end_epoch}) via {url}...")
    with httpx.Client(cookies=cookies, headers=headers, timeout=20.0) as client:
        response = client.post(url)
        response.raise_for_status()
        
        # El servidor de la Secretaria Virtual de la UPF pot retornar dades en ISO-8859-1 (Latin-1)
        try:
            content_text = response.content.decode("utf-8")
        except UnicodeDecodeError:
            content_text = response.content.decode("iso-8859-1")

        stripped_content = content_text.strip() if content_text else ""
        if not stripped_content:
            logger.info("La resposta HTTP de la UPF està buida. S'interpreta com a 0 sessions.")
            raw_json = []
        else:
            try:
                raw_json = json.loads(stripped_content)
            except json.JSONDecodeError as err:
                logger.error(f"Resposta no vàlida en format JSON ({err}): {stripped_content[:200]}")
                raise RuntimeError(
                    f"La resposta de la UPF no és un JSON vàlid ({err}). "
                    f"Possible fallada del servei o sessió invàlida: {stripped_content[:200]}"
                )

        if not isinstance(raw_json, list):
            logger.error(f"La resposta de la UPF té un format no esperat (no és una llista): {raw_json}")
            raise RuntimeError("La resposta de la Secretaria Virtual de la UPF no conté una llista de sessions vàlida.")

    week_sessions = parse_raw_sessions(raw_json, settings.TIMEZONE)
    target_sessions = [s for s in week_sessions if monday <= s.start_time.date() <= sunday]
    unique_target = deduplicate_sessions(target_sessions)
    unique_target.sort(key=lambda s: s.start_time)
    logger.info(f"S'han trobat {len(unique_target)} sessions oficials per a la setmana {monday} a {sunday}.")
    return unique_target
