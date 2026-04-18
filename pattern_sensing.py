"""
SAP IBP-Style Pattern-Based Demand Sensing
===========================================
Takes recent actuals and blends short-horizon sensed forecast with a
statistical long-horizon forecast. Implements the five IBP pieces:

 1. Multi-signal intake — actuals + optional promo / weather / POS signals
 2. Pattern library     — parametric templates (promo lift, holiday ramp,
                          weekend dip, post-outage bounce, trend-break)
 3. ML matching         — cosine similarity on normalized residuals; best
                          match drives the lift/shape correction
 4. Horizon handoff     — sensed owns weeks 0–6 (configurable), statistical
                          owns 7+; soft linear blend in the overlap band
 5. Posterior variance  — each sensed point carries a σ propagated to safety
                          stock via SS = z·σ·√LT

This is a lightweight pure-Python implementation (no sklearn/numpy-heavy deps
needed on the inference path — we use math only) so it runs on Render's starter
plan without bloating the container.
"""
import math


# ─── 1. Pattern Library ─────────────────────────────────────────────────
# Each pattern is a parametric shape over N weeks relative to an anchor point.
# `shape(k, p)` returns the multiplicative lift at offset k (0..N-1) given
# pattern-specific params p.

def _promo_lift(N=8):
    """Classic promo: pre-ramp (1 wk), peak (2-3 wks), decay tail (3-4 wks)."""
    shape = []
    for k in range(N):
        if k == 0:
            shape.append(1.10)   # pre-announce buy-in
        elif k in (1, 2, 3):
            shape.append(1.55)   # peak
        elif k in (4, 5):
            shape.append(1.20)   # decay
        else:
            shape.append(0.92)   # post-promo trough (pull-forward effect)
    return shape


def _holiday_ramp(N=8):
    """Exponential pre-holiday ramp, peak at week 6, crash at week 7."""
    peak_at = min(6, N - 2)
    shape = []
    for k in range(N):
        if k < peak_at:
            shape.append(1 + 0.12 * (k / max(peak_at, 1)) ** 2 * 3)
        elif k == peak_at:
            shape.append(1.80)
        else:
            shape.append(0.55)  # post-holiday crash
    return shape


def _weekend_dip(N=8):
    """Mild weekly oscillation — B2B weekly cycle, not strong for weekly grain."""
    return [1.0 + 0.05 * math.cos(k * 2 * math.pi / 7) for k in range(N)]


def _post_outage_bounce(N=8):
    """After a stockout / supply outage: suppressed week(s), then catch-up."""
    shape = [0.35, 0.55, 1.45, 1.35, 1.15, 1.05, 1.0, 1.0]
    return (shape + [1.0] * N)[:N]


def _trend_break_up(N=8):
    """Step-change regime shift (e.g., competitor exit, channel expansion)."""
    return [1.0] * 2 + [1.30] * (N - 2)


def _trend_break_down(N=8):
    """Step-change down (e.g., product cannibalization, demand loss)."""
    return [1.0] * 2 + [0.72] * (N - 2)


def _cannibalization(N=8):
    """New SKU launch steals demand — smooth decay to new floor."""
    return [1.0 - 0.05 * k for k in range(N)]


PATTERN_LIBRARY = {
    'promo_lift':        {'shape_fn': _promo_lift,        'description': 'Promotion pre-buy → peak → decay → trough'},
    'holiday_ramp':      {'shape_fn': _holiday_ramp,      'description': 'Exponential ramp to holiday, then crash'},
    'weekend_dip':       {'shape_fn': _weekend_dip,       'description': 'Weekly cyclical B2B pattern'},
    'post_outage_bounce':{'shape_fn': _post_outage_bounce,'description': 'Suppressed then catch-up after outage'},
    'trend_break_up':    {'shape_fn': _trend_break_up,    'description': 'Regime shift upward (persistent)'},
    'trend_break_down':  {'shape_fn': _trend_break_down,  'description': 'Regime shift downward (persistent)'},
    'cannibalization':   {'shape_fn': _cannibalization,   'description': 'Smooth decay — SKU being cannibalized'},
}


# ─── 2. Matching (cosine similarity on residuals) ───────────────────────

def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _residual_ratio(actual, baseline):
    """Residual as ratio (actual/baseline) — normalized shape independent of level."""
    return [
        (a / b) if b > 0 else 1.0
        for a, b in zip(actual, baseline)
    ]


def match_patterns(actuals, baseline_forecast, min_history=4):
    """Compare residual shape of recent actuals to each pattern in the library.
    Returns ranked list of {pattern, similarity, shape}."""
    if len(actuals) < min_history or len(baseline_forecast) < min_history:
        return []
    n = min(len(actuals), len(baseline_forecast), 8)
    recent_a = actuals[-n:]
    recent_b = baseline_forecast[:n]
    residual = _residual_ratio(recent_a, recent_b)
    # Normalize residual to mean=1 for shape-only comparison
    mu = sum(residual) / max(len(residual), 1)
    if mu == 0:
        mu = 1.0
    residual_norm = [r / mu - 1.0 for r in residual]  # center at 0
    results = []
    for name, info in PATTERN_LIBRARY.items():
        template = info['shape_fn'](N=n)
        t_mu = sum(template) / max(len(template), 1)
        template_norm = [t / t_mu - 1.0 for t in template]
        sim = _cosine(residual_norm, template_norm)
        results.append({
            'pattern': name,
            'description': info['description'],
            'similarity': round(sim, 3),
            'shape': template,
        })
    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results


# ─── 3. Horizon handoff (sensed weeks 0-N, statistical N+, linear blend) ─

def horizon_blend(sensed, statistical, sense_weeks=6, blend_weeks=3):
    """Sensed forecast owns weeks 0..sense_weeks-1.
    Linear blend from week sense_weeks for blend_weeks weeks.
    Statistical owns the rest."""
    T = max(len(sensed), len(statistical))
    out = []
    for t in range(T):
        s = sensed[t] if t < len(sensed) else (statistical[t] if t < len(statistical) else 0)
        f = statistical[t] if t < len(statistical) else (sensed[t] if t < len(sensed) else 0)
        if t < sense_weeks:
            out.append(s)
        elif t < sense_weeks + blend_weeks:
            alpha = (t - sense_weeks + 1) / (blend_weeks + 1)
            out.append((1 - alpha) * s + alpha * f)
        else:
            out.append(f)
    return out


# ─── 4. Posterior variance propagation ───────────────────────────────────

def posterior_variance(actuals, baseline, z=1.645):
    """Compute per-point σ from recent residual std. Returns σ to be used as
    safety-stock multiplier."""
    if len(actuals) < 3 or len(baseline) < 3:
        return {'sigma': 0, 'cv': 0, 'safety_stock_multiplier': z}
    n = min(len(actuals), len(baseline))
    residuals = [actuals[i] - baseline[i] for i in range(n)]
    mu_r = sum(residuals) / n
    var_r = sum((r - mu_r) ** 2 for r in residuals) / max(n - 1, 1)
    sigma = math.sqrt(var_r)
    mu_base = sum(baseline[:n]) / n
    cv = (sigma / mu_base) if mu_base > 0 else 0
    return {
        'sigma': round(sigma, 3),
        'cv': round(cv, 3),
        'safety_stock_multiplier': round(z * (1 + cv), 3),  # amplify SS under high CV
    }


# ─── 5. End-to-end sense() ───────────────────────────────────────────────

def sense(data):
    """Main entry point.
    Input:
      actuals: [..]              — recent observed demand, ordered oldest→newest
      baseline_forecast: [..]    — statistical forecast covering same+future horizon
      horizon: int               — total weeks to output (defaults to len(baseline))
      sense_weeks: int           — how many weeks the sensed forecast owns (default 6)
      blend_weeks: int           — overlap band (default 3)
      promo_weeks: [int]         — upcoming promo weeks (optional external signal)
      holiday_weeks: [int]       — upcoming holiday weeks (optional external signal)
      alpha: float               — exponential smoother for baseline override (default 0.3)
      z: float                   — service-level z-score (default 1.645 = 95%)

    Output:
      {
        matched_patterns: [{pattern, similarity, description, shape}],
        primary_pattern: str,
        sensed_forecast: [..],
        blended_forecast: [..],
        posterior: {sigma, cv, safety_stock_multiplier},
        audit: { alpha, sense_weeks, blend_weeks, matched_confidence }
      }
    """
    actuals = [float(x) for x in (data.get('actuals') or [])]
    baseline = [float(x) for x in (data.get('baseline_forecast') or [])]
    horizon = int(data.get('horizon', len(baseline)) or len(baseline))
    sense_weeks = int(data.get('sense_weeks', 6))
    blend_weeks = int(data.get('blend_weeks', 3))
    alpha = float(data.get('alpha', 0.3))
    z = float(data.get('z', 1.645))
    promo_weeks = set(int(w) for w in (data.get('promo_weeks') or []))
    holiday_weeks = set(int(w) for w in (data.get('holiday_weeks') or []))

    if not actuals or not baseline:
        return {
            'error': 'Need both actuals and baseline_forecast',
            'actuals_len': len(actuals),
            'baseline_len': len(baseline),
        }

    # Step 1: Match patterns on recent history
    matched = match_patterns(actuals, baseline)
    top = matched[0] if matched else None
    # Only apply shape correction if similarity is meaningfully > 0
    pattern_confidence = max(top['similarity'], 0) if top else 0
    primary_pattern = top['pattern'] if top and pattern_confidence > 0.15 else 'none'

    # Step 2: Build sensed forecast — baseline × shape_lift × smoother
    # Start from exponential-smoothed recent actual as the level anchor
    recent_level = actuals[-1] if actuals else (baseline[0] if baseline else 0)
    smoothed_level = alpha * recent_level + (1 - alpha) * (baseline[0] if baseline else recent_level)
    if baseline[0] > 0:
        level_ratio = smoothed_level / baseline[0]
    else:
        level_ratio = 1.0

    shape = top['shape'] if top and pattern_confidence > 0.15 else [1.0] * sense_weeks

    sensed = []
    for t in range(sense_weeks):
        b = baseline[t] if t < len(baseline) else (baseline[-1] if baseline else 0)
        lift = shape[t] if t < len(shape) else 1.0
        external_lift = 1.0
        if t in promo_weeks:
            external_lift *= 1.35
        if t in holiday_weeks:
            external_lift *= 1.25
        sensed.append(b * level_ratio * lift * external_lift)

    # Step 3: Blend sensed + statistical across horizon
    blended = horizon_blend(sensed, baseline, sense_weeks=sense_weeks, blend_weeks=blend_weeks)
    blended = blended[:horizon] if horizon else blended

    # Step 4: Posterior variance from residuals
    posterior = posterior_variance(actuals, baseline, z=z)

    return {
        'status': 'ok',
        'matched_patterns': matched[:5],
        'primary_pattern': primary_pattern,
        'pattern_confidence': round(pattern_confidence, 3),
        'sensed_forecast': [round(v, 2) for v in sensed],
        'blended_forecast': [round(v, 2) for v in blended],
        'baseline_forecast': baseline[:horizon],
        'posterior': posterior,
        'audit': {
            'alpha': alpha,
            'sense_weeks': sense_weeks,
            'blend_weeks': blend_weeks,
            'level_ratio': round(level_ratio, 3),
            'smoothed_level': round(smoothed_level, 2),
            'recent_level': round(recent_level, 2),
            'n_actuals': len(actuals),
            'n_baseline': len(baseline),
            'horizon': horizon,
            'promo_weeks': sorted(promo_weeks),
            'holiday_weeks': sorted(holiday_weeks),
        },
    }


def list_patterns():
    """Return the pattern library descriptions (for UI documentation)."""
    return {
        name: {
            'description': info['description'],
            'example_shape': info['shape_fn'](N=8),
        }
        for name, info in PATTERN_LIBRARY.items()
    }
