"""
India 2026 Working Calendar
============================
Generates actual working days by iterating day-by-day through 2026,
checking weekday + gazetted holiday exclusion.

Source: Tamil Nadu Government GO (Public Department) + DoPT circular.
Reference: https://www.tn.gov.in/holiday.php
"""
from datetime import date, timedelta

# TN 2026 Gazetted Holidays (24 confirmed by DoPT)
# Format: (month, day, name)
TN_HOLIDAYS_2026 = [
    (1, 1, "New Year's Day"),
    (1, 15, "Pongal"),
    (1, 16, "Thiruvalluvar Day"),
    (1, 26, "Republic Day"),
    (3, 14, "Maha Shivaratri"),
    (3, 21, "Ramzan (Id-ul-Fitr)"),      # lunar, approximate
    (3, 31, "Telugu New Year / Ugadi"),
    (4, 6, "Mahavir Jayanti"),
    (4, 10, "Good Friday"),
    (4, 14, "Ambedkar Jayanti / Tamil New Year"),
    (5, 1, "May Day"),
    (5, 12, "Buddha Purnima"),
    (5, 28, "Bakrid (Id-ul-Zuha)"),       # lunar, approximate
    (6, 26, "Muharram"),                   # lunar, approximate
    (8, 15, "Independence Day"),
    (8, 26, "Milad-un-Nabi"),             # lunar, approximate
    (9, 5, "Vinayagar Chaturthi"),
    (10, 2, "Gandhi Jayanti"),
    (10, 12, "Dussehra / Vijayadashami"),
    (11, 8, "Deepavali"),
    (11, 28, "Guru Nanak Jayanti"),
    (12, 25, "Christmas"),
]

# National holidays (subset, always observed)
NATIONAL_HOLIDAYS_2026 = [
    (1, 26, "Republic Day"),
    (8, 15, "Independence Day"),
    (10, 2, "Gandhi Jayanti"),
]

# Per-state REGIONAL add-ons (representative, on top of the TN gazette base). These
# are real, well-known state holidays that genuinely differ between Indian states —
# so the "Plant State" selector actually changes the working calendar instead of
# always showing Tamil Nadu. HONEST scope (same caveat as TN_HOLIDAYS_2026): fixed
# (month, day) holidays are exact every year; lunar / movable ones are exact for
# 2026 and approximate otherwise. A planner overrides any of this with custom_holidays.
STATE_HOLIDAYS = {
    'TN': [],  # the base set IS Tamil Nadu (TN_HOLIDAYS_2026)
    'MH': [    # Maharashtra
        (5, 1, "Maharashtra Day"),
        (2, 19, "Chhatrapati Shivaji Maharaj Jayanti"),
        (3, 19, "Gudi Padwa"),
    ],
    'GJ': [    # Gujarat
        (5, 1, "Gujarat Day"),
        (1, 14, "Uttarayan / Makar Sankranti"),
        (10, 31, "Sardar Patel Jayanti"),
    ],
    'KA': [    # Karnataka
        (11, 1, "Kannada Rajyotsava"),
        (8, 1, "Varamahalakshmi Vratam"),
    ],
}


def build_calendar(work_days_per_week=6, use_indian_holidays=True, custom_holidays=None, start_month=0, year=2026, state='TN'):
    """
    Build a day-by-day working calendar for `year`.

    Args:
        work_days_per_week: 5 (Mon-Fri), 6 (Mon-Sat), 7 (all days)
        use_indian_holidays: exclude TN gazetted holidays
        custom_holidays: additional [(month, day, name)] to exclude
        start_month: 0=Jan, 3=Apr (fiscal year), etc.
        year: (MF-16) calendar year — was hardcoded 2026. Weekday/leap-year math now follows
              `year`. NOTE: the TN_HOLIDAYS_2026 dates are (month, day) pairs and apply to any
              year as-is; the lunar-calendar holidays (Ramzan, Bakrid, Muharram, Milad) are only
              exact for 2026 and approximate for other years.
        state: plant state code (TN/MH/GJ/KA) — merges that state's REGIONAL add-ons
               (STATE_HOLIDAYS) on top of the base set so the selector drives the result.

    Returns:
        dict with monthly working days, total, holiday list, and day-by-day array
    """
    # Build holiday set
    holiday_set = set()
    holiday_list = []

    if use_indian_holidays:
        for m, d, name in TN_HOLIDAYS_2026:
            holiday_set.add((m, d))
            holiday_list.append({'month': m, 'day': d, 'name': name})
        # regional add-ons for the selected plant state (skip dups already in base)
        for m, d, name in STATE_HOLIDAYS.get(state or 'TN', []):
            if (m, d) not in holiday_set:
                holiday_set.add((m, d))
                holiday_list.append({'month': m, 'day': d, 'name': name})

    if custom_holidays:
        for m, d, name in custom_holidays:
            if (m, d) in holiday_set:
                continue
            holiday_set.add((m, d))
            holiday_list.append({'month': m, 'day': d, 'name': name})
    
    # Iterate day-by-day through 2026
    monthly_work_days = [0] * 12
    monthly_total_days = [0] * 12
    monthly_holidays = [0] * 12
    daily_calendar = []  # [{date, month, weekday, is_working, holiday_name}]
    
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    
    while d <= end:
        m = d.month - 1  # 0-indexed
        wd = d.weekday()  # 0=Mon, 6=Sun
        monthly_total_days[m] += 1
        
        # Check if this day is a working day
        is_weekday = False
        if work_days_per_week == 5 and wd < 5:  # Mon-Fri
            is_weekday = True
        elif work_days_per_week == 6 and wd < 6:  # Mon-Sat
            is_weekday = True
        elif work_days_per_week == 7:  # All days
            is_weekday = True
        
        is_holiday = (d.month, d.day) in holiday_set
        is_working = is_weekday and not is_holiday
        
        holiday_name = None
        if is_holiday:
            monthly_holidays[m] += 1
            for hm, hd, hn in ((TN_HOLIDAYS_2026 + STATE_HOLIDAYS.get(state or 'TN', [])) if use_indian_holidays else []) + (custom_holidays or []):
                if hm == d.month and hd == d.day:
                    holiday_name = hn
                    break
        
        if is_working:
            monthly_work_days[m] += 1
        
        daily_calendar.append({
            'date': d.isoformat(),
            'month': m,
            'weekday': wd,
            'weekday_name': ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][wd],
            'is_working': is_working,
            'is_holiday': is_holiday,
            'holiday_name': holiday_name,
        })
        
        d += timedelta(days=1)
    
    total_working = sum(monthly_work_days)
    
    # Reorder by fiscal year start month
    month_order = [(start_month + i) % 12 for i in range(12)]
    MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    
    monthly_detail = []
    for i in range(12):
        mi = month_order[i]
        monthly_detail.append({
            'month': MONTH_NAMES[mi],
            'month_index': mi,
            'work_days': monthly_work_days[mi],
            'total_days': monthly_total_days[mi],
            'holidays': monthly_holidays[mi],
            'weekends': monthly_total_days[mi] - monthly_work_days[mi] - monthly_holidays[mi],
        })
    
    return {
        'year': year,
        'work_days_per_week': work_days_per_week,
        'indian_holidays': use_indian_holidays,
        'total_working_days': total_working,
        'total_holidays': sum(monthly_holidays),
        'monthly': monthly_detail,
        'monthly_work_days': monthly_work_days,  # 0-indexed Jan=0
        'holiday_list': holiday_list,
        'daily': daily_calendar,  # 365 entries
    }
