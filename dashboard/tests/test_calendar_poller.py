import importlib.util
from datetime import date
from pathlib import Path


def _load_calendar_poller():
    module_path = Path(__file__).resolve().parents[2] / "bin" / "calendar-poller.py"
    spec = importlib.util.spec_from_file_location("calendar_poller", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compute_fetch_window_midweek():
    module = _load_calendar_poller()
    start, end = module.compute_fetch_window(date(2026, 3, 4))

    assert start == date(2026, 3, 4)
    assert end == date(2026, 3, 8)


def test_compute_fetch_window_sunday_rolls_forward():
    module = _load_calendar_poller()
    start, end = module.compute_fetch_window(date(2026, 3, 8))

    assert start == date(2026, 3, 8)
    assert end == date(2026, 3, 15)


def test_format_event_summary_uses_readable_start_label():
    module = _load_calendar_poller()
    summary = module.format_event_summary(
        {
            "summary": "Planning Review",
            "start": "2026-03-09T14:30:00-08:00",
        }
    )

    assert summary == "Mon 03/09 14:30 — Planning Review"


def test_fetch_events_fans_out_by_day_and_dedupes(monkeypatch):
    module = _load_calendar_poller()
    requested_dates = []
    responses = {
        date(2026, 3, 9): [
            {"id": "evt-1", "summary": "Sprint Planning", "start": "2026-03-09T07:30:00-07:00", "end": "2026-03-09T08:00:00-07:00"},
        ],
        date(2026, 3, 10): [
            {"id": "evt-1", "summary": "Sprint Planning", "start": "2026-03-09T07:30:00-07:00", "end": "2026-03-09T08:00:00-07:00"},
            {"id": "evt-2", "summary": "Weekly Sync", "start": "2026-03-10T11:00:00-07:00", "end": "2026-03-10T11:30:00-07:00"},
        ],
    }

    monkeypatch.setattr(module, "compute_fetch_window", lambda today=None: (date(2026, 3, 9), date(2026, 3, 11)))

    def fake_fetch(target_date):
        requested_dates.append(target_date)
        return responses.get(target_date, [])

    monkeypatch.setattr(module, "_fetch_events_for_date", fake_fetch)

    events = module.fetch_events()

    assert requested_dates == [date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 11)]
    assert events == [
        {"id": "evt-1", "summary": "Sprint Planning", "start": "2026-03-09T07:30:00-07:00", "end": "2026-03-09T08:00:00-07:00"},
        {"id": "evt-2", "summary": "Weekly Sync", "start": "2026-03-10T11:00:00-07:00", "end": "2026-03-10T11:30:00-07:00"},
    ]
