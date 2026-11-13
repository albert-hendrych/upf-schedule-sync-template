from datetime import date, datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
from src.calendar_manager import CalendarManager
from src.models import ClassSession, CalendarEvent


def test_get_events_for_date_parses_items():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api

    mock_events_api.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt123",
                "summary": "Sistemes Operatius [Teoria]",
                "location": "Aula 52.217",
                "start": {"dateTime": "2026-10-08T09:00:00+02:00"},
                "end": {"dateTime": "2026-10-08T11:00:00+02:00"},
                "description": "Classe UPF",
                "colorId": "6"
            }
        ]
    }

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    events = manager.get_events_for_date(date(2026, 10, 8))

    assert len(events) == 1
    assert events[0].event_id == "evt123"
    assert events[0].location == "Aula 52.217"
    assert events[0].color_id == "6"
    assert events[0].start_time.hour == 9


def test_create_event_public_visibility():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api
    mock_events_api.insert.return_value.execute.return_value = {"id": "new_evt_456"}
    mock_events_api.list.return_value.execute.return_value = {"items": []}

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    tz = ZoneInfo("Europe/Madrid")
    session = ClassSession(
        subject_name="Xarxes",
        start_time=datetime(2026, 10, 8, 12, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 14, 0, tzinfo=tz),
        classroom="Aula 52.115",
        session_type="Laboratori"
    )

    new_id = manager.create_event(session)
    assert new_id == "new_evt_456"
    assert mock_events_api.insert.called
    call_args = mock_events_api.insert.call_args[1]
    assert call_args["body"]["visibility"] == "public"


def test_create_event_copies_color_from_cache():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api
    mock_events_api.insert.return_value.execute.return_value = {"id": "new_evt_789"}

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    # Pre-populate color cache for "Xarxes"
    manager._color_cache["xarxes"] = "4"

    tz = ZoneInfo("Europe/Madrid")
    session = ClassSession(
        subject_name="Xarxes [Teoria]",
        start_time=datetime(2026, 10, 8, 12, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 14, 0, tzinfo=tz),
        classroom="Aula 52.115"
    )

    manager.create_event(session)
    call_args = mock_events_api.insert.call_args[1]
    assert call_args["body"]["visibility"] == "public"
    assert call_args["body"]["colorId"] == "4"


def test_create_event_copies_color_from_api_search():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api
    mock_events_api.insert.return_value.execute.return_value = {"id": "new_evt_999"}
    # API search returns an existing event with colorId
    mock_events_api.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "existing_1",
                "summary": "Comunicació Tècnica en Anglès [Teoria]",
                "colorId": "7"
            }
        ]
    }

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    tz = ZoneInfo("Europe/Madrid")
    session = ClassSession(
        subject_name="Comunicació Tècnica en Anglès",
        start_time=datetime(2026, 10, 8, 15, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 17, 0, tzinfo=tz),
        classroom="Aula 52.217",
        session_type="Seminari",
        group_id="S201"
    )

    manager.create_event(session)
    call_args = mock_events_api.insert.call_args[1]
    assert call_args["body"]["visibility"] == "public"
    assert call_args["body"]["colorId"] == "7"


def test_update_event_classroom():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    manager.update_event_classroom("evt123", "Aula 13.002")
    assert mock_events_api.patch.called
    call_args = mock_events_api.patch.call_args[1]
    assert call_args["body"] == {"location": "Aula 13.002"}


def test_mark_event_cancelled():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    manager.mark_event_cancelled("evt123", "Sistemes Operatius")
    assert mock_events_api.patch.called
    call_args = mock_events_api.patch.call_args[1]
    assert call_args["body"] == {"summary": "[CANCEL·LADA] Sistemes Operatius"}


def test_restore_event():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    manager.restore_event("evt123", "[CANCEL·LADA] Sistemes Operatius [Teoria]")
    assert mock_events_api.patch.called
    call_args = mock_events_api.patch.call_args[1]
    assert call_args["body"] == {"summary": "Sistemes Operatius [Teoria]"}


def test_get_events_for_week():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api
    mock_events_api.list.return_value.execute.return_value = {"items": []}

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    # Date is Thursday 2026-10-22. Week should span Monday 2026-10-19 to Sunday 2026-10-25
    manager.get_events_for_week(date(2026, 10, 22))

    assert mock_events_api.list.called
    call_args = mock_events_api.list.call_args[1]
    assert "2026-10-19T00:00:00" in call_args["timeMin"]
    assert "2026-10-25T23:59:59" in call_args["timeMax"]


def test_update_event_time_and_classroom():
    mock_service = MagicMock()
    mock_events_api = MagicMock()
    mock_service.events.return_value = mock_events_api

    manager = CalendarManager(service=mock_service, calendar_id="test@calendar.com")
    tz = ZoneInfo("Europe/Madrid")
    new_start = datetime(2026, 10, 21, 10, 30, tzinfo=tz)
    new_end = datetime(2026, 10, 21, 12, 30, tzinfo=tz)

    manager.update_event_time_and_classroom(
        event_id="evt_move_1",
        new_start=new_start,
        new_end=new_end,
        new_classroom="Aula 52.321",
        current_summary="[CANCEL·LADA] Simulació de Xarxes [Pràctiques]"
    )

    assert mock_events_api.patch.called
    call_args = mock_events_api.patch.call_args[1]
    assert call_args["eventId"] == "evt_move_1"
    assert call_args["body"]["start"]["dateTime"] == new_start.isoformat()
    assert call_args["body"]["end"]["dateTime"] == new_end.isoformat()
    assert call_args["body"]["location"] == "Aula 52.321"
    # Strips previous CANCEL·LADA tag when moving to new valid slot
    assert call_args["body"]["summary"] == "Simulació de Xarxes [Pràctiques]"
