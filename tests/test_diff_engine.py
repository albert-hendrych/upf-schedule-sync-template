from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from src.models import ClassSession, CalendarEvent, DiffType
from src.diff_engine import compare_schedules


def test_diff_detects_room_change():
    tz = ZoneInfo("Europe/Madrid")
    start = datetime(2026, 10, 8, 9, 0, tzinfo=tz)
    end = datetime(2026, 10, 8, 11, 0, tzinfo=tz)

    web_session = ClassSession(
        subject_name="Sistemes Operatius",
        start_time=start,
        end_time=end,
        classroom="Aula 13.002"
    )
    cal_event = CalendarEvent(
        event_id="e1",
        summary="Sistemes Operatius [Teoria]",
        start_time=start,
        end_time=end,
        location="Aula 52.217"
    )

    diffs = compare_schedules([web_session], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.ROOM_CHANGE
    assert diffs[0].old_value == "Aula 52.217"
    assert diffs[0].new_value == "Aula 13.002"
    assert "Canvi d'aula" in diffs[0].message


def test_diff_detects_cancellation():
    tz = ZoneInfo("Europe/Madrid")
    cal_event = CalendarEvent(
        event_id="e2",
        summary="Xarxes de Computadors",
        start_time=datetime(2026, 10, 8, 15, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 17, 0, tzinfo=tz),
        location="Aula 52.115"
    )
    diffs = compare_schedules([], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.CANCELLED
    assert "cancel·lada" in diffs[0].message.lower()


def test_diff_detects_new_session():
    tz = ZoneInfo("Europe/Madrid")
    web_session = ClassSession(
        subject_name="Intel·ligència Artificial",
        start_time=datetime(2026, 10, 8, 11, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 13, 0, tzinfo=tz),
        classroom="Aula 52.217"
    )
    diffs = compare_schedules([web_session], [])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.NEW_SESSION
    assert "Nova classe" in diffs[0].message


def test_diff_matches_within_15_minutes_tolerance():
    tz = ZoneInfo("Europe/Madrid")
    # Web starts at 09:10, Google Calendar had 09:00 (10 min diff <= 15 min tolerance)
    web_session = ClassSession(
        subject_name="Sistemes Operatius",
        start_time=datetime(2026, 10, 8, 9, 10, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 11, 0, tzinfo=tz),
        classroom="Aula 52.217"
    )
    cal_event = CalendarEvent(
        event_id="e3",
        summary="Sistemes Operatius",
        start_time=datetime(2026, 10, 8, 9, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 11, 0, tzinfo=tz),
        location="Aula 52.217"
    )
    diffs = compare_schedules([web_session], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.UNCHANGED


def test_diff_matches_with_course_code_prefix():
    tz = ZoneInfo("Europe/Madrid")
    # UPF title has course code prefix: '23974 - Simulació i Modelització de Xarxes'
    # Calendar has: 'Simulació i Modelització de Xarxes [Pràctiques]'
    web_session = ClassSession(
        subject_name="23974 - Simulació i Modelització de Xarxes",
        start_time=datetime(2026, 10, 8, 8, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 10, 30, tzinfo=tz),
        classroom="Aula 52.321"
    )
    cal_event = CalendarEvent(
        event_id="e4",
        summary="Simulació i Modelització de Xarxes [Pràctiques]",
        start_time=datetime(2026, 10, 8, 8, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 10, 30, tzinfo=tz),
        location="Aula 52.321"
    )
    diffs = compare_schedules([web_session], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.UNCHANGED


def test_diff_detects_restored_session():
    tz = ZoneInfo("Europe/Madrid")
    web_session = ClassSession(
        subject_name="23974 - Simulació i Modelització de Xarxes",
        start_time=datetime(2026, 10, 8, 8, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 10, 30, tzinfo=tz),
        classroom="Aula 52.321"
    )
    # The event in Google Calendar was marked [CANCEL·LADA] in a prior run
    cal_event = CalendarEvent(
        event_id="e5",
        summary="[CANCEL·LADA] Simulació i Modelització de Xarxes [Pràctiques]",
        start_time=datetime(2026, 10, 8, 8, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 8, 10, 30, tzinfo=tz),
        location="Aula 52.321"
    )
    diffs = compare_schedules([web_session], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.RESTORED
    assert "reactivada" in diffs[0].message.lower() or "confirmada" in diffs[0].message.lower()


def test_diff_detects_time_change_rescheduled_day_in_week():
    tz = ZoneInfo("Europe/Madrid")
    # Google Calendar previously had class on Thursday 2026-10-22 at 08:30
    cal_event = CalendarEvent(
        event_id="cal_thursday_1",
        summary="Simulació i Modelització de Xarxes [Pràctiques]",
        start_time=datetime(2026, 10, 22, 8, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 22, 10, 30, tzinfo=tz),
        location="Aula 52.321"
    )
    # UPF moved the class to Wednesday 2026-10-21 at 10:30
    web_session = ClassSession(
        subject_name="Simulació i Modelització de Xarxes",
        session_type="Pràctiques",
        start_time=datetime(2026, 10, 21, 10, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 21, 12, 30, tzinfo=tz),
        classroom="Aula 52.321"
    )

    diffs = compare_schedules([web_session], [cal_event])
    # Must produce exactly 1 diff of type TIME_CHANGE (no duplicate NEW_SESSION and no CANCELLED)
    assert len(diffs) == 1
    d = diffs[0]
    assert d.diff_type == DiffType.TIME_CHANGE
    assert d.calendar_event.event_id == "cal_thursday_1"
    assert d.web_session.start_time == datetime(2026, 10, 21, 10, 30, tzinfo=tz)
    assert "Canvi de dia/horari" in d.message
    assert "Dijous" in d.message
    assert "Dimecres" in d.message


def test_diff_preserves_separate_activity_types_when_rescheduling():
    tz = ZoneInfo("Europe/Madrid")
    # Calendar has:
    # 1. Teoria on Monday 2026-10-19 09:00
    # 2. Pràctiques on Thursday 2026-10-22 15:00
    cal_teoria = CalendarEvent(
        event_id="cal_teoria_1",
        summary="Sistemes Operatius [Teoria]",
        start_time=datetime(2026, 10, 19, 9, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 19, 11, 0, tzinfo=tz),
        location="Aula 52.217"
    )
    cal_prac = CalendarEvent(
        event_id="cal_prac_1",
        summary="Sistemes Operatius [Pràctiques]",
        start_time=datetime(2026, 10, 22, 15, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 22, 17, 0, tzinfo=tz),
        location="Aula 52.115"
    )

    # UPF has:
    # 1. Teoria moved to Tuesday 2026-10-20 11:00
    # 2. Pràctiques still on Thursday 2026-10-22 15:00
    web_teoria = ClassSession(
        subject_name="Sistemes Operatius",
        session_type="Teoria",
        start_time=datetime(2026, 10, 20, 11, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 20, 13, 0, tzinfo=tz),
        classroom="Aula 52.217"
    )
    web_prac = ClassSession(
        subject_name="Sistemes Operatius",
        session_type="Pràctiques",
        start_time=datetime(2026, 10, 22, 15, 0, tzinfo=tz),
        end_time=datetime(2026, 10, 22, 17, 0, tzinfo=tz),
        classroom="Aula 52.115"
    )

    diffs = compare_schedules([web_teoria, web_prac], [cal_teoria, cal_prac])
    assert len(diffs) == 2

    # Pràctiques must be UNCHANGED
    prac_diff = next(d for d in diffs if d.web_session.session_type == "Pràctiques")
    assert prac_diff.diff_type == DiffType.UNCHANGED

    # Teoria must be TIME_CHANGE (matched with cal_teoria_1, NOT cal_prac_1)
    teoria_diff = next(d for d in diffs if d.web_session.session_type == "Teoria")
    assert teoria_diff.diff_type == DiffType.TIME_CHANGE
    assert teoria_diff.calendar_event.event_id == "cal_teoria_1"


def test_diff_detects_room_change_from_placeholder_to_extracted_room():
    tz = ZoneInfo("Europe/Madrid")
    start = datetime(2026, 10, 23, 9, 0, tzinfo=tz)
    end = datetime(2026, 10, 23, 11, 0, tzinfo=tz)

    web_session = ClassSession(
        subject_name="Transmissió Digital de Dades",
        start_time=start,
        end_time=end,
        classroom="Aula 52.019"
    )
    cal_event = CalendarEvent(
        event_id="e_placeholder",
        summary="Transmissió Digital de Dades",
        start_time=start,
        end_time=end,
        location="Sense aules assignades"
    )

    diffs = compare_schedules([web_session], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.ROOM_CHANGE
    assert diffs[0].old_value == "Sense aules assignades"
    assert diffs[0].new_value == "Aula 52.019"
    assert "Canvi d'aula" in diffs[0].message


def test_diff_matches_classroom_normalization_ignoring_aula_prefix():
    tz = ZoneInfo("Europe/Madrid")
    start = datetime(2026, 10, 23, 9, 0, tzinfo=tz)
    end = datetime(2026, 10, 23, 11, 0, tzinfo=tz)

    web_session = ClassSession(
        subject_name="Transmissió Digital de Dades",
        start_time=start,
        end_time=end,
        classroom="Aula 52.019"
    )
    cal_event = CalendarEvent(
        event_id="e_same_room",
        summary="Transmissió Digital de Dades",
        start_time=start,
        end_time=end,
        location="52.019"
    )

    diffs = compare_schedules([web_session], [cal_event])
    assert len(diffs) == 1
    assert diffs[0].diff_type == DiffType.UNCHANGED

