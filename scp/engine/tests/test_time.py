from datetime import date

from scp.model import Calendar, Settings
from scp.time import Buckets, WorkCalendar

MON_FRI = WorkCalendar(Calendar(id="C", workdays=[0, 1, 2, 3, 4], holidays=[date(2026, 1, 7)]))


def test_workday_arithmetic():
    mon = date(2026, 1, 5)
    assert MON_FRI.is_workday(mon)
    assert not MON_FRI.is_workday(date(2026, 1, 7))           # holiday
    assert not MON_FRI.is_workday(date(2026, 1, 10))          # Saturday
    assert MON_FRI.add_workdays(mon, 0) == mon
    assert MON_FRI.add_workdays(mon, 2) == date(2026, 1, 8)   # skips the Wednesday holiday
    assert MON_FRI.add_workdays(date(2026, 1, 9), 1) == date(2026, 1, 12)  # Fri → Mon
    assert MON_FRI.add_workdays(date(2026, 1, 12), -1) == date(2026, 1, 9)
    assert MON_FRI.add_workdays(mon, 1.2) == date(2026, 1, 8)  # fractional rounds up: 2 working days
    assert MON_FRI.workdays_between(mon, date(2026, 1, 12)) == 4
    assert MON_FRI.next_workday(date(2026, 1, 10)) == date(2026, 1, 12)
    assert MON_FRI.prev_workday(date(2026, 1, 11)) == date(2026, 1, 9)


def test_week_buckets_align_to_week_start():
    s = Settings(planning_start=date(2026, 1, 7), horizon_days=21, bucket="week")  # a Wednesday
    b = Buckets(s)
    assert b[0].start == date(2026, 1, 7) and b[0].end == date(2026, 1, 12)  # partial first week
    assert all(x.start.weekday() == 0 for x in list(b)[1:])
    assert b[-1].end == date(2026, 1, 28)
    assert sum(x.days for x in b) == 21
    assert b.index_of(date(2026, 1, 6)) == -1
    assert b.index_of(date(2026, 1, 12)) == 1
    assert b.index_of(date(2026, 1, 28)) == len(b)


def test_month_buckets_and_labels():
    s = Settings(planning_start=date(2026, 1, 20), horizon_days=60, bucket="month")
    b = Buckets(s)
    assert [x.label for x in b] == ["Jan 2026", "Feb 2026", "Mar 2026"]
    assert b[1].start == date(2026, 2, 1) and b[1].days == 28


def test_day_buckets():
    s = Settings(planning_start=date(2026, 1, 5), horizon_days=7, bucket="day")
    b = Buckets(s)
    assert len(b) == 7 and b[0].label.startswith("Mon 05 Jan")
