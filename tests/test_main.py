from datetime import date
from unittest.mock import patch, MagicMock
from src.main import run_pipeline
from src.models import DiffResult, DiffType, ClassSession, CalendarEvent


@patch("src.main.login_and_get_cookies")
@patch("src.main.fetch_schedule")
@patch("src.main.CalendarManager")
@patch("src.main.compare_schedules")
@patch("src.main.send_telegram_alert")
def test_run_pipeline_success(mock_alert, mock_compare, mock_cal_cls, mock_fetch, mock_login):
    mock_login.return_value = {"JSESSIONID": "123"}
    mock_fetch.return_value = []

    mock_cal_instance = MagicMock()
    mock_cal_instance.get_events_for_date.return_value = []
    mock_cal_instance.get_events_for_week.return_value = []
    mock_cal_cls.return_value = mock_cal_instance

    mock_compare.return_value = [
        DiffResult(
            diff_type=DiffType.ROOM_CHANGE,
            subject_name="Sistemes",
            old_value="52.217",
            new_value="13.002",
            message="Canvi d'aula"
        )
    ]

    exit_code = run_pipeline(target_date=date(2026, 10, 8), dry_run=False)
    assert exit_code == 0
    assert mock_alert.called


@patch("src.main.login_and_get_cookies")
@patch("src.main.fetch_schedule")
@patch("src.main.CalendarManager")
@patch("src.main.compare_schedules")
@patch("src.main.send_telegram_alert")
def test_run_pipeline_dry_run(mock_alert, mock_compare, mock_cal_cls, mock_fetch, mock_login):
    mock_login.return_value = {"JSESSIONID": "123"}
    mock_fetch.return_value = []

    mock_cal_instance = MagicMock()
    mock_cal_instance.get_events_for_date.return_value = []
    mock_cal_instance.get_events_for_week.return_value = []
    mock_cal_cls.return_value = mock_cal_instance

    mock_compare.return_value = [
        DiffResult(
            diff_type=DiffType.ROOM_CHANGE,
            subject_name="Sistemes",
            old_value="52.217",
            new_value="13.002",
            message="Canvi d'aula"
        )
    ]

    exit_code = run_pipeline(target_date=date(2026, 10, 8), dry_run=True)
    assert exit_code == 0
    # In dry-run, alert is not sent and calendar is not modified
    assert not mock_alert.called
    assert not mock_cal_instance.update_event_classroom.called


@patch("src.main.login_and_get_cookies")
@patch("src.main.fetch_schedule")
@patch("src.main.CalendarManager")
@patch("src.main.compare_schedules")
@patch("src.main.send_telegram_alert")
def test_run_pipeline_applies_time_change(mock_alert, mock_compare, mock_cal_cls, mock_fetch, mock_login):
    mock_login.return_value = {"JSESSIONID": "123"}
    mock_fetch.return_value = []

    mock_cal_instance = MagicMock()
    mock_cal_instance.get_events_for_week.return_value = []
    mock_cal_cls.return_value = mock_cal_instance

    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Madrid")
    cal_evt = CalendarEvent(
        event_id="e_time_1",
        summary="Xarxes [Pràctiques]",
        start_time=datetime(2026, 10, 22, 8, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 22, 10, 30, tzinfo=tz)
    )
    web_sess = ClassSession(
        subject_name="Xarxes",
        session_type="Pràctiques",
        start_time=datetime(2026, 10, 21, 10, 30, tzinfo=tz),
        end_time=datetime(2026, 10, 21, 12, 30, tzinfo=tz),
        classroom="Aula 52.321"
    )

    mock_compare.return_value = [
        DiffResult(
            diff_type=DiffType.TIME_CHANGE,
            subject_name="Xarxes",
            calendar_event=cal_evt,
            web_session=web_sess,
            message="Canvi de dia/horari"
        )
    ]

    exit_code = run_pipeline(target_date=date(2026, 10, 22), dry_run=False)
    assert exit_code == 0
    assert mock_cal_instance.update_event_time_and_classroom.called
    call_kwargs = mock_cal_instance.update_event_time_and_classroom.call_args[1]
    assert call_kwargs["event_id"] == "e_time_1"
    assert call_kwargs["new_start"] == datetime(2026, 10, 21, 10, 30, tzinfo=tz)
    assert call_kwargs["new_classroom"] == "Aula 52.321"


@patch("src.main.login_and_get_cookies")
def test_run_pipeline_auth_failure(mock_login):
    from src.auth import AuthenticationError
    mock_login.side_effect = AuthenticationError("Credencials incorrectes")

    exit_code = run_pipeline(target_date=date(2026, 10, 8), dry_run=False)
    assert exit_code == 1


def test_get_default_target_date_weekday():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.main import get_default_target_date

    # Thursday Oct 8 -> returns Oct 8 (current week)
    fake_now = datetime(2026, 10, 8, 15, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    with patch("src.main.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        res = get_default_target_date("Europe/Madrid")
        assert res == date(2026, 10, 8)


def test_get_default_target_date_weekend_saturday():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.main import get_default_target_date

    # Saturday Oct 10 -> targets next Monday (Oct 12)
    fake_now = datetime(2026, 10, 10, 15, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    with patch("src.main.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        res = get_default_target_date("Europe/Madrid")
        assert res == date(2026, 10, 12)


def test_get_default_target_date_weekend_sunday():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.main import get_default_target_date

    # Sunday Oct 11 -> targets next Monday (Oct 12)
    fake_now = datetime(2026, 10, 11, 15, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    with patch("src.main.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        res = get_default_target_date("Europe/Madrid")
        assert res == date(2026, 10, 12)

