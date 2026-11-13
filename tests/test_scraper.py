from datetime import date
import pytest
import respx
from src.scraper import (
    parse_raw_sessions,
    is_placeholder_classroom,
    extract_classroom_from_notes,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from src.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parse_raw_sessions_filters_holidays_and_cleans_entities():
    raw_data = [
        {
            "title": "Programaci&oacute; Orientada a Objectes",
            "start": "2026-10-08 09:00:00",
            "end": "2026-10-08 11:00:00",
            "aula": "Aula 52.217",
            "tipologia": "Teoria",
            "grup": "101",
            "codAsignatura": "21415",
            "profesores": ["Garc&iacute;a, Joan"],
            "festivoNoLectivo": False
        },
        {
            "title": "Festa Major",
            "start": "2026-10-08 11:00:00",
            "end": "2026-10-08 19:00:00",
            "festivoNoLectivo": True
        },
        {
            "other_stuff": "invalid"
        }
    ]

    sessions = parse_raw_sessions(raw_data, "Europe/Madrid")
    assert len(sessions) == 1
    session = sessions[0]
    assert session.subject_name == "Programació Orientada a Objectes"
    assert session.classroom == "Aula 52.217"
    assert session.teachers == ["García, Joan"]
    assert session.start_time.hour == 9
    assert session.end_time.hour == 11
    assert str(session.start_time.tzinfo) == "Europe/Madrid"


@respx.mock
def test_fetch_schedule_network_call(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    route = respx.post(url__regex=r"https://secretariavirtual\.upf\.edu/.*").respond(
        200,
        json=[
            {
                "title": "Estructures de Dades",
                "start": "2026-10-08 15:00:00",
                "end": "2026-10-08 17:00:00",
                "aula": "Aula 52.115",
                "tipologia": "Seminari",
                "festivoNoLectivo": False
            }
        ]
    )
    from src.scraper import fetch_schedule
    res = fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 8))
    assert len(res) == 1
    assert res[0].subject_name == "Estructures de Dades"
    assert route.called


@respx.mock
def test_fetch_schedule_iso8859_1_encoding(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    # Simulate binary response containing byte 0xf3 ("ó" in latin-1)
    iso_bytes = b'[{"title": "Gesti\xf3 de Projectes", "start": "2026-10-08 10:00:00", "end": "2026-10-08 12:00:00", "aula": "Aula 52.217"}]'
    respx.post(url__regex=r"https://secretariavirtual\.upf\.edu/.*").respond(
        200,
        content=iso_bytes,
        headers={"Content-Type": "application/json"}
    )
    from src.scraper import fetch_schedule
    res = fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 8))
    assert len(res) == 1
    assert res[0].subject_name == "Gestió de Projectes"
    assert res[0].classroom == "Aula 52.217"


def test_parse_raw_sessions_iso_datetime():
    raw_data = [
        {
            "title": "Simulació de Xarxes",
            "start": "2026-10-08T08:30:00+02:00",
            "end": "2026-10-08T10:30:00+02:00",
            "aula": "Aula 52.321",
            "festivoNoLectivo": False
        }
    ]
    sessions = parse_raw_sessions(raw_data, "Europe/Madrid")
    assert len(sessions) == 1
    assert sessions[0].start_time.hour == 8
    assert sessions[0].start_time.minute == 30


@respx.mock
def test_fetch_schedule_returns_week_sessions(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    # Simulate UPF returning sessions: Wednesday 7, Thursday 8 (same week), and next week Monday 12
    week_data = [
        {
            "title": "Classe Dimecres",
            "start": "2026-10-07 10:00:00",
            "end": "2026-10-07 12:00:00",
            "aula": "Aula 52.019",
            "festivoNoLectivo": False
        },
        {
            "title": "Classe Dijous",
            "start": "2026-10-08 08:30:00",
            "end": "2026-10-08 10:30:00",
            "aula": "Aula 52.321",
            "festivoNoLectivo": False
        },
        {
            "title": "Classe Setmana Vinent",
            "start": "2026-10-12 09:00:00",
            "end": "2026-10-12 11:00:00",
            "aula": "Aula 52.100",
            "festivoNoLectivo": False
        }
    ]
    respx.post(url__regex=r"https://secretariavirtual\.upf\.edu/.*").respond(
        200,
        json=week_data
    )
    from src.scraper import fetch_schedule
    # Requesting the week of Thursday 2026-10-08 (Oct 5 to Oct 11)
    res = fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 8))
    assert len(res) == 2
    titles = [s.subject_name for s in res]
    assert "Classe Dimecres" in titles
    assert "Classe Dijous" in titles
    assert "Classe Setmana Vinent" not in titles


def test_fetch_schedule_uses_intercepted_sessions_when_range_covers_week(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    from zoneinfo import ZoneInfo
    from datetime import datetime
    from src import auth
    auth.clear_intercepted_sessions()
    tz = ZoneInfo("Europe/Madrid")
    
    # Range covers full week of Oct 5 - Oct 11
    auth._INTERCEPTED_START_EPOCH = int(datetime(2026, 10, 5, 0, 0, 0, tzinfo=tz).timestamp())
    auth._INTERCEPTED_END_EPOCH = int(datetime(2026, 10, 11, 23, 59, 59, tzinfo=tz).timestamp())
    auth._INTERCEPTED_SESSIONS.append({
        "title": "Classe Interceptada",
        "start": "2026-10-08 08:30:00",
        "end": "2026-10-08 10:30:00",
        "aula": "Aula 52.321",
        "festivoNoLectivo": False
    })

    from src.scraper import fetch_schedule
    res = fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 8))
    assert len(res) == 1
    assert res[0].subject_name == "Classe Interceptada"
    auth.clear_intercepted_sessions()


def test_fetch_schedule_queries_network_when_intercepted_sessions_partially_overlap(monkeypatch):
    """
    Cas real del dissabte 24:
    El navegador va interceptar sessions des del dilluns 19 fins al dilluns 26 al matí.
    Com que contenia 1 classe del dilluns 26, no cobria la resta de la setmana (26 oct - 1 nov).
    fetch_schedule ha de detectar que el rang NO cobreix tota la setmana i consultar la xarxa!
    """
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    import respx
    from zoneinfo import ZoneInfo
    from datetime import datetime
    from src import auth
    auth.clear_intercepted_sessions()
    tz = ZoneInfo("Europe/Madrid")

    # Range ends on Monday 26 Oct morning (10:00) instead of Sunday 1 Nov
    auth._INTERCEPTED_START_EPOCH = int(datetime(2026, 10, 19, 0, 0, 0, tzinfo=tz).timestamp())
    auth._INTERCEPTED_END_EPOCH = int(datetime(2026, 10, 26, 10, 0, 0, tzinfo=tz).timestamp())
    auth._INTERCEPTED_ENDPOINT_URL = "https://matricula.upf.edu/pds/control/[Ajax]selecionarRangoHorarios"

    # Only 1 class was in the intercepted slice
    auth._INTERCEPTED_SESSIONS.append({
        "title": "Classe Dilluns Matí",
        "start": "2026-10-26 08:30:00",
        "end": "2026-10-26 10:30:00",
        "aula": "Aula 52.019",
        "festivoNoLectivo": False
    })

    # The network must be called on matricula.upf.edu and return all 10 classes
    with respx.mock:
        route = respx.post(url__regex=r"https://matricula\.upf\.edu/.*").respond(
            200,
            json=[
                {
                    "title": "Classe Dilluns Matí",
                    "start": "2026-10-26 08:30:00",
                    "end": "2026-10-26 10:30:00",
                    "aula": "Aula 52.019",
                    "festivoNoLectivo": False
                },
                {
                    "title": "Simulació i Modelització de Xarxes",
                    "start": "2026-10-27 10:30:00",
                    "end": "2026-10-27 12:30:00",
                    "aula": "Aula 52.217",
                    "festivoNoLectivo": False
                }
            ]
        )
        from src.scraper import fetch_schedule
        res = fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 26))

        # Because intercepted range only went up to Oct 26 morning, the full week was NOT covered,
        # so it must have fetched the full week via the detected endpoint!
        assert route.called
        assert len(res) == 2
        assert res[0].subject_name == "Classe Dilluns Matí"
        assert res[1].subject_name == "Simulació i Modelització de Xarxes"

    auth.clear_intercepted_sessions()


@respx.mock
def test_fetch_schedule_empty_http_response_handled_gracefully(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    from src import auth
    auth.clear_intercepted_sessions()

    # Simulate HTTP 200 with completely empty body
    respx.post(url__regex=r"https://secretariavirtual\.upf\.edu/.*").respond(
        200,
        content=b""
    )
    from src.scraper import fetch_schedule
    res = fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 10))
    assert res == []


@respx.mock
def test_fetch_schedule_non_json_http_response_raises_error(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Madrid")
    from src import auth
    auth.clear_intercepted_sessions()

    # Simulate non-JSON response (e.g. error HTML or session expired)
    respx.post(url__regex=r"https://secretariavirtual\.upf\.edu/.*").respond(
        200,
        content=b"<html><body>Error de sessio</body></html>"
    )
    from src.scraper import fetch_schedule
    with pytest.raises(RuntimeError, match="no és un JSON vàlid"):
        fetch_schedule(cookies={"JSESSIONID": "xyz"}, target_date=date(2026, 10, 10))


def test_parse_subject_group_filters_formats():
    from src.scraper import parse_subject_group_filters

    assert parse_subject_group_filters("") == {}
    assert parse_subject_group_filters(None) == {}

    compact = parse_subject_group_filters("23962:S201,P201; Comunicació Tècnica en Anglès: 102")
    assert compact == {
        "23962": ["S201", "P201"],
        "comunicaciotecnicaenangles": ["102"],
    }

    as_json = parse_subject_group_filters('{"23962": ["s201", "p201"], "Xarxes": "S101"}')
    assert as_json == {
        "23962": ["S201", "P201"],
        "xarxes": ["S101"],
    }

    # Invalid inputs should not raise
    assert parse_subject_group_filters("{invalid_json") == {}
    assert parse_subject_group_filters("missing_colon_entry") == {}


def test_is_session_relevant_allows_all_when_no_filter_configured(monkeypatch):
    from src.scraper import is_session_relevant
    from src.models import ClassSession
    from src.config import get_settings
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("SUBJECT_GROUP_FILTERS", "")
    get_settings.cache_clear()

    tz = ZoneInfo("Europe/Madrid")
    base_time = datetime(2026, 10, 8, 10, 0, tzinfo=tz)

    sem_202 = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        raw_id="23962",
        start_time=base_time,
        end_time=base_time,
        session_type="Seminari",
        group_id="S202"
    )
    assert is_session_relevant(sem_202) is True


def test_is_session_relevant_with_configured_group_filter(monkeypatch):
    from src.scraper import is_session_relevant
    from src.models import ClassSession
    from src.config import get_settings
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("SUBJECT_GROUP_FILTERS", "23962:S201,P201;Comunicació Tècnica en Anglès:S201,P201")
    get_settings.cache_clear()

    tz = ZoneInfo("Europe/Madrid")
    base_time = datetime(2026, 10, 8, 10, 0, tzinfo=tz)

    # 1. Teoria -> ha de ser rellevant sempre
    teoria = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        raw_id="23962",
        start_time=base_time,
        end_time=base_time,
        session_type="Teoria",
        group_id="101"
    )
    assert is_session_relevant(teoria) is True

    # 2. Seminari S201 -> rellevant
    sem_201 = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        raw_id="23962",
        start_time=base_time,
        end_time=base_time,
        session_type="Seminari",
        group_id="S201"
    )
    assert is_session_relevant(sem_201) is True

    # 3. Pràctica P201 -> rellevant
    prac_201 = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        raw_id="23962",
        start_time=base_time,
        end_time=base_time,
        session_type="Pràctiques",
        group_id="P201"
    )
    assert is_session_relevant(prac_201) is True

    # 4. Seminari S202 -> NO rellevant (grup diferent)
    sem_202 = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        raw_id="23962",
        start_time=base_time,
        end_time=base_time,
        session_type="Seminari",
        group_id="S202"
    )
    assert is_session_relevant(sem_202) is False

    # 5. Pràctica P202 -> NO rellevant
    prac_202 = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        raw_id="23962",
        start_time=base_time,
        end_time=base_time,
        session_type="Pràctiques",
        group_id="P202"
    )
    assert is_session_relevant(prac_202) is False

    # 6. Altra assignatura amb grup S202 -> rellevant (no s'ha de filtrar)
    other_sem_202 = ClassSession(
        subject_name="Sistemes Operatius",
        raw_id="21415",
        start_time=base_time,
        end_time=base_time,
        session_type="Seminari",
        group_id="S202"
    )
    assert is_session_relevant(other_sem_202) is True


def test_parse_raw_sessions_filters_configured_groups(monkeypatch):
    from src.config import get_settings

    monkeypatch.setenv("SUBJECT_GROUP_FILTERS", "23962:S201,P201")
    get_settings.cache_clear()

    raw_data = [
        {
            "title": "Comunicació Tècnica en Anglès",
            "codAsignatura": "23962",
            "start": "2026-10-08 09:00:00",
            "end": "2026-10-08 11:00:00",
            "tipologia": "Teoria",
            "grup": "101",
            "festivoNoLectivo": False
        },
        {
            "title": "Comunicació Tècnica en Anglès",
            "codAsignatura": "23962",
            "start": "2026-10-08 11:00:00",
            "end": "2026-10-08 13:00:00",
            "tipologia": "Seminari",
            "grup": "S201",
            "festivoNoLectivo": False
        },
        {
            "title": "Comunicació Tècnica en Anglès",
            "codAsignatura": "23962",
            "start": "2026-10-08 11:00:00",
            "end": "2026-10-08 13:00:00",
            "tipologia": "Seminari",
            "grup": "S202",
            "festivoNoLectivo": False
        },
        {
            "title": "Comunicació Tècnica en Anglès",
            "codAsignatura": "23962",
            "start": "2026-10-08 15:00:00",
            "end": "2026-10-08 17:00:00",
            "tipologia": "Pràctiques",
            "grup": "P201",
            "festivoNoLectivo": False
        },
        {
            "title": "Comunicació Tècnica en Anglès",
            "codAsignatura": "23962",
            "start": "2026-10-08 15:00:00",
            "end": "2026-10-08 17:00:00",
            "tipologia": "Pràctiques",
            "grup": "P202",
            "festivoNoLectivo": False
        },
        {
            "title": "Xarxes de Computadors",
            "codAsignatura": "21499",
            "start": "2026-10-08 17:00:00",
            "end": "2026-10-08 19:00:00",
            "tipologia": "Seminari",
            "grup": "S202",
            "festivoNoLectivo": False
        }
    ]

    sessions = parse_raw_sessions(raw_data, "Europe/Madrid")
    # Es deuen haver mantingut: Teoria, S201, P201, i Xarxes S202
    assert len(sessions) == 4
    groups = [(s.subject_name, s.session_type, s.group_id) for s in sessions]
    assert ("Comunicació Tècnica en Anglès", "Teoria", "101") in groups
    assert ("Comunicació Tècnica en Anglès", "Seminari", "S201") in groups
    assert ("Comunicació Tècnica en Anglès", "Pràctiques", "P201") in groups
    assert ("Xarxes de Computadors", "Seminari", "S202") in groups
    assert ("Comunicació Tècnica en Anglès", "Seminari", "S202") not in groups
    assert ("Comunicació Tècnica en Anglès", "Pràctiques", "P202") not in groups


def test_is_placeholder_classroom():
    assert is_placeholder_classroom("Sense aules assignades") is True
    assert is_placeholder_classroom("Sense aules assignades.") is True
    assert is_placeholder_classroom("Sense aula") is True
    assert is_placeholder_classroom("Sin aulas asignadas") is True
    assert is_placeholder_classroom("Pendent d'assignar") is True
    assert is_placeholder_classroom("") is True
    assert is_placeholder_classroom(None) is True
    assert is_placeholder_classroom("Aula 52.217") is False
    assert is_placeholder_classroom("Laboratori 54.004") is False


def test_extract_classroom_from_notes():
    # User's exact example:
    notes1 = "Aula 52.019. Grups S101, S102, S103 i S104 junts a la mateixa aula."
    assert extract_classroom_from_notes(notes1) == "Aula 52.019"

    # Pattern with Lab
    notes2 = "La sessió tindrà lloc al Lab 54.004 per a tots els alumnes."
    assert extract_classroom_from_notes(notes2) == "Laboratori 54.004"

    # Pattern with isolated room number XX.YYY
    notes3 = "Atenció: canvi a la 52.019."
    assert extract_classroom_from_notes(notes3) == "Aula 52.019"

    # Pattern with Aula Magna
    notes4 = "Sessió inaugural a l'Aula Magna."
    assert extract_classroom_from_notes(notes4) == "Aula Magna"

    # Notes without room
    notes5 = "Porteu el portàtil carregat i instal·lat el programari."
    assert extract_classroom_from_notes(notes5) is None
    assert extract_classroom_from_notes(None) is None


def test_parse_raw_sessions_extracts_classroom_when_placeholder():
    raw_data = [
        {
            "title": "Transmissió Digital de Dades",
            "start": "2026-10-23 09:00:00",
            "end": "2026-10-23 11:00:00",
            "aula": "Sense aules assignades",
            "observacion": "Aula 52.019. Grups S101, S102, S103 i S104 junts a la mateixa aula.",
            "tipologia": "Seminari",
            "festivoNoLectivo": False
        },
        {
            "title": "Teoria del Senyal",
            "start": "2026-10-23 11:00:00",
            "end": "2026-10-23 13:00:00",
            "aula": "Sense aules assignades",
            "observacion": "Classe normal, porteu apunts.",
            "tipologia": "Teoria",
            "festivoNoLectivo": False
        }
    ]

    sessions = parse_raw_sessions(raw_data, "Europe/Madrid")
    assert len(sessions) == 2

    # First session: extracted from notes
    assert sessions[0].subject_name == "Transmissió Digital de Dades"
    assert sessions[0].classroom == "Aula 52.019"
    assert "Grups S101" in sessions[0].notes

    # Second session: placeholder with no room in notes becomes "Sense aula"
    assert sessions[1].subject_name == "Teoria del Senyal"
    assert sessions[1].classroom == "Sense aula"



