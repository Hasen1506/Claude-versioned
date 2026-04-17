"""
Hierarchical Planning Disaggregation
======================================
Takes high-level aggregate plans and disaggregates them down to
operational granularity:

  Annual profit mix quantities
    → Monthly using seasonal profile (from forecast)
      → Weekly using working day calendar
        → Daily using shift schedule

This bridges the data granularity gap between:
  - Profit Maximizer (annual/quarterly)
  - Procurement Optimizer (weekly)
  - Production Scheduler (daily/shift)
"""
import math


def disaggregate(data):
    """
    Input:
      products: [{name, annual_qty, forecast_monthly[12], ...}]
      calendar: {work_days_per_week, holidays[], start_month}
    
    Output:
      Per product: monthly[], weekly[], daily[] quantities
    """
    products = data.get('products', [])
    calendar = data.get('calendar', {})
    work_days = calendar.get('work_days_per_week', 6)
    start_month = calendar.get('start_month', 0)  # 0=Jan

    # Working days per month (India 2026 approximate)
    MONTH_WORK_DAYS = {
        5: [22, 20, 23, 21, 22, 21, 23, 22, 20, 23, 21, 20],  # 5-day week
        6: [26, 24, 27, 25, 26, 25, 27, 26, 24, 27, 25, 24],  # 6-day week
        7: [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31],  # 7-day week
    }
    wd_per_month = MONTH_WORK_DAYS.get(work_days, MONTH_WORK_DAYS[6])

    # Reorder months based on start_month (fiscal year)
    month_order = [(start_month + i) % 12 for i in range(12)]
    MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

    results = []

    for prod in products:
        annual_qty = prod.get('annual_qty', 0)
        forecast = prod.get('forecast_monthly', [])
        name = prod.get('name', 'Product')

        if not annual_qty and not forecast:
            results.append({'name': name, 'error': 'No annual_qty or forecast provided'})
            continue

        # ── Step 1: Annual → Monthly ──
        # Use seasonal profile from forecast to distribute annual quantity
        if forecast and len(forecast) >= 12 and sum(forecast) > 0:
            total_forecast = sum(forecast)
            # Seasonal proportion per month
            seasonal_pct = [f / total_forecast for f in forecast]
            monthly = [round(annual_qty * pct) for pct in seasonal_pct]
            # Adjust rounding error
            diff = annual_qty - sum(monthly)
            if diff != 0:
                # Add/subtract from the largest month
                max_idx = monthly.index(max(monthly))
                monthly[max_idx] += diff
            method_monthly = 'seasonal_profile'
        else:
            # Even distribution
            base = annual_qty // 12
            remainder = annual_qty % 12
            monthly = [base + (1 if i < remainder else 0) for i in range(12)]
            method_monthly = 'even_distribution'

        # ── Step 2: Monthly → Weekly ──
        weekly = []
        week_labels = []
        week_num = 1
        for m in range(12):
            cal_month = month_order[m]
            wd = wd_per_month[cal_month]
            # Weeks in this month (approx 4-5)
            weeks_in_month = max(1, round(wd / work_days))
            month_qty = monthly[m]

            # Distribute monthly qty across weeks proportionally to working days
            wd_per_week_arr = []
            remaining_wd = wd
            for w in range(weeks_in_month):
                if w < weeks_in_month - 1:
                    wwd = work_days  # standard week
                else:
                    wwd = remaining_wd  # last week gets remainder
                wd_per_week_arr.append(wwd)
                remaining_wd -= work_days

            total_week_wd = sum(wd_per_week_arr)
            for w in range(weeks_in_month):
                wk_qty = round(month_qty * wd_per_week_arr[w] / max(total_week_wd, 1))
                weekly.append(wk_qty)
                week_labels.append(f"W{week_num} ({MONTH_NAMES[cal_month][:3]})")
                week_num += 1

        # Adjust weekly to match annual
        weekly_total = sum(weekly)
        if weekly_total != annual_qty and len(weekly) > 0:
            diff = annual_qty - weekly_total
            # Spread adjustment across peak weeks
            sorted_idx = sorted(range(len(weekly)), key=lambda i: weekly[i], reverse=True)
            for i in range(abs(diff)):
                idx = sorted_idx[i % len(sorted_idx)]
                weekly[idx] += 1 if diff > 0 else -1

        # ── Step 3: Weekly → Daily ──
        daily = []
        day_labels = []
        for wi, wk_qty in enumerate(weekly):
            days_this_week = min(work_days, 7)
            base_daily = wk_qty // days_this_week
            remainder_daily = wk_qty % days_this_week
            for d in range(days_this_week):
                dq = base_daily + (1 if d < remainder_daily else 0)
                daily.append(dq)
                day_labels.append(f"D{len(daily)}")

        results.append({
            'name': name,
            'annual_qty': annual_qty,
            'method_monthly': method_monthly,
            'monthly': monthly,
            'monthly_labels': [MONTH_NAMES[month_order[i]] for i in range(12)],
            'weekly': weekly,
            'weekly_labels': week_labels,
            'n_weeks': len(weekly),
            'daily': daily,
            'n_days': len(daily),
            'daily_avg': round(sum(daily) / max(len(daily), 1), 1),
            'daily_max': max(daily) if daily else 0,
            'daily_min': min(daily) if daily else 0,
            # Validation
            'monthly_total': sum(monthly),
            'weekly_total': sum(weekly),
            'daily_total': sum(daily),
            'balanced': sum(monthly) == annual_qty and sum(weekly) == annual_qty,
        })

    return {
        'status': 'ok',
        'products': results,
        'calendar': {
            'work_days_per_week': work_days,
            'start_month': MONTH_NAMES[start_month],
            'month_order': [MONTH_NAMES[m] for m in month_order],
        },
    }
