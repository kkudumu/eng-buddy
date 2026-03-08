import importlib.util
from pathlib import Path
from datetime import date


def _load_calendar_poller():
    module_path = Path(__file__).resolve().parents[2] / "bin" / "calendar-poller.py"
    spec = importlib.util.spec_from_file_location("calendar_poller", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compute_fetch_window_midweek():
    module = _load_calendar_poller()
    start, end = module.compute_fetch_window(date(2026, 3, 4))  # Wednesday

    assert start == date(2026, 3, 4)
    assert end == date(2026, 3, 8)


def test_compute_fetch_window_sunday_rolls_forward():
    module = _load_calendar_poller()
    start, end = module.compute_fetch_window(date(2026, 3, 8))  # Sunday

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
