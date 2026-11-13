from datetime import datetime
from zoneinfo import ZoneInfo
from src.models import ClassSession, CalendarEvent, DiffType, DiffResult


def test_class_session_creation():
    madrid = ZoneInfo("Europe/Madrid")
    start = datetime(2026, 10, 8, 9, 0, tzinfo=madrid)
    end = datetime(2026, 10, 8, 11, 0, tzinfo=madrid)

    session = ClassSession(
        subject_name="Sistemes Operatius",
        start_time=start,
        end_time=end,
        classroom="Aula 52.217",
        group_id="101",
        session_type="Teoria",
        teachers=["Joan Garcia"]
    )
    assert session.subject_name == "Sistemes Operatius"
    assert session.classroom == "Aula 52.217"
    assert session.teachers == ["Joan Garcia"]
    assert session.session_type == "Teoria"


def test_diff_result():
    diff = DiffResult(
        diff_type=DiffType.ROOM_CHANGE,
        subject_name="Sistemes Operatius",
        old_value="Aula 52.217",
        new_value="Aula 13.002",
        message="Canvi d'aula a Sistemes Operatius: Aula 52.217 -> Aula 13.002"
    )
    assert diff.diff_type == DiffType.ROOM_CHANGE
    assert "Aula 13.002" in diff.message
    assert diff.old_value == "Aula 52.217"
    assert diff.new_value == "Aula 13.002"
