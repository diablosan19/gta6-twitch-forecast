"""The forecaster: comparable-shape quantile regression in log space.

Why this shape of model (see DATA.md for the evidence): a launch day's Twitch curve,
measured as log v(h) - log v(1) for hours h = 2..24, is not a random walk around
persistence. It is mostly determined by *when the world unlocks relative to 00:00 UTC*:

  - rolling midnight-local launches (NZ/AU unlock ~11:00-13:00Z on day -1) have a real
    but trough-level hour 1, then build to a peak at hours 16-23 of 1.3x-12x hour 1;
  - single global unlocks during the UTC day have a near-zero, pre-unlock hour 1 and
    explode by 60x-2000x once the unlock hour passes;
  - launches already live at hour 1 (global unlock <= 00:00Z, or multi-day early
    access) decay from hour 1.

The case file carries 38 past launches ("comparables") with full hourly curves. This
model therefore does no parametric shape fitting at all: it takes the empirical
distribution of the comparables' log-ratio curves, weighted by how similar each
comparable is to the target on the features knowable at the hour-1 checkpoint, and
reads the forecast quantiles off that weighted distribution:

  shape s(h)      = weighted median of L_c(h) = log v_c(h) - log v_c(1),
                    shrunk toward 0 (persistence) by the effective sample size;
  spread at h     = weighted quantiles of the residuals L_c(h') - s(h'), pooled over
                    the neighbouring hours h' in {h-1, h, h+1}, blended 50/50 with a
                    normal law of the same weighted standard deviation, so the tails
                    stay sane when the effective pool is thin;
  q_tau(h)        = v1 * exp(s(h) + rq_tau(h)).

Similarity features (computed identically for target and comparables, from data that
ends at the checkpoint): log10 of hour-1 viewers, log of the pre-release peak ratio
(max viewers in the 24 h before day_start, over v1), log of the pre-release mean
ratio over the same window, and a soft prior from the unlock prose (rolling / global /
early-access / unknown): agreeing classes multiply a comparable's weight by 2,
disagreeing ones by 0.45. Nothing is hardcoded per game, nothing is read from the
network, and every number comes from the case file at runtime. If the pool is unusable
the model falls back to the house persistence forecast, so a pathological case scores
like the baseline instead of invalid.
"""

import math
import re
from datetime import datetime, timedelta, timezone

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (the baseline's z values).
Z = [-1.645, -0.674, 0, 0.674, 1.645]
# The baseline's log-space spread per square-root hour (the fallback law).
BASE_SIGMA = 0.15

# --- tuning constants (chosen a priori, checked once by leave-one-out backtest) ---
CLASS_AGREE = 2.0        # weight multiplier when unlock classes agree
CLASS_DISAGREE = 0.45    # ... and when they disagree
SHAPE_SHRINK_K = 3.0     # shape *= n_eff / (n_eff + K): thin evidence -> persistence
RESID_NORMAL_BLEND = 0.5 # residual quantiles: half empirical, half fitted normal


def parse_time(text):
    """An ISO-8601 '...Z' timestamp as an aware datetime (None when unparseable)."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def hourly_viewers(points):
    """{datetime: viewers} from a SullyGnome-style point list ('from' or 'at' keyed)."""
    out = {}
    for row in points or []:
        t = parse_time(row.get("from") or row.get("at"))
        v = row.get("viewers")
        if t is not None and isinstance(v, (int, float)):
            out[t] = float(v)
    return out


# ---------------------------------------------------------------- features

def pre_release_features(series, day_start, v1):
    """The checkpoint features from the 24 h before day_start, or None values.

    Returns (log10_v1, log_pre_peak_ratio, log_pre_mean_ratio); a ratio entry is None
    when the window holds no usable point, so distance computations can skip it.
    """
    pre = [v for t, v in series.items() if day_start - timedelta(hours=24) <= t < day_start]
    log_v1 = math.log10(max(v1, 1.0))
    if not pre:
        return (log_v1, None, None)
    peak = max(pre) / v1
    mean = (sum(pre) / len(pre)) / v1
    return (
        log_v1,
        math.log(peak) if peak > 0 else None,
        math.log(mean) if mean > 0 else None,
    )


_TIME_RE = re.compile(r"(\d{1,2}):00\s*(?:Z|UTC)")


def unlock_class(text):
    """A coarse read of the unlock prose: 'global', 'early', 'rolling' or 'unknown'.

    Deliberately a soft prior only: much of the prose is 'unverified', so the class
    merely tilts the similarity weights; the curve features do the real work.
    """
    t = (text or "").lower()
    has_time = _TIME_RE.search(t) is not None
    if ("global" in t or "simultaneous" in t) and has_time:
        return "global"
    if "early access" in t or "early-access" in t:
        return "early"
    if "rolling" in t or "midnight local" in t:
        return "rolling"
    return "unknown"


# ---------------------------------------------------------------- pool

def comparable_curve(comp):
    """One comparable's release-day log-ratio curve, or None when it has no launch day.

    Returns (features, {hour: log v(h) - log v(1)}). A comparable is usable only when
    its series holds an hour-1 point on its own day_start with viewers >= 1 and at
    least 12 of hours 2..24; the pre-release GTA VI category entry fails this by
    construction (its 'day_start' is a premiere, not a launch).
    """
    day_start = parse_time(comp.get("day_start"))
    if day_start is None:
        return None
    series = hourly_viewers(comp.get("hourly"))
    v1 = series.get(day_start)
    if v1 is None or v1 < 1:
        return None
    curve = {}
    for h in range(2, 25):
        v = series.get(day_start + timedelta(hours=h - 1))
        if v is not None and v > 0:
            curve[h] = math.log(v) - math.log(v1)
    if len(curve) < 12:
        return None
    feats = pre_release_features(series, day_start, v1)
    return feats, curve, unlock_class(comp.get("unlock"))


def weighted_quantile(pairs, tau):
    """The tau-quantile of [(value, weight)] by linear interpolation on cum. weight."""
    pts = sorted(pairs)
    total = sum(w for _, w in pts)
    if total <= 0:
        return pts[0][0]
    target = tau * total
    acc = 0.0
    for i, (v, w) in enumerate(pts):
        acc += w
        if acc >= target:
            if i == 0:
                return v
            prev_v, prev_w = pts[i - 1]
            prev_acc = acc - w
            frac = 0.0 if w == 0 else (target - prev_acc) / w
            return prev_v + frac * (v - prev_v)
    return pts[-1][0]


def similarity_weights(target_feats, target_class, pool):
    """Gaussian-kernel weights of the pool [(feats, curve, class)] for the target.

    Features are standardised by the pool's own spread, so the kernel measures
    distance in 'typical variation' units; features missing on either side are
    skipped for that pair. Also returns the effective sample size (sum w)^2/sum w^2.
    """
    scales = []
    for j in range(3):
        vals = [f[j] for f, _, _ in pool if f[j] is not None]
        if len(vals) < 2:
            scales.append(None)
            continue
        mean = sum(vals) / len(vals)
        var = sum((x - mean) ** 2 for x in vals) / len(vals)
        scales.append(math.sqrt(var) if var > 0 else None)
    weights = []
    for feats, _, cls in pool:
        d2 = 0.0
        for j in range(3):
            if target_feats[j] is None or feats[j] is None or scales[j] is None:
                continue
            d2 += ((target_feats[j] - feats[j]) / scales[j]) ** 2
        w = math.exp(-0.5 * d2)
        if target_class != "unknown" and cls != "unknown":
            w *= CLASS_AGREE if cls == target_class else CLASS_DISAGREE
        weights.append(w)
    total = sum(weights)
    n_eff = (total * total / sum(w * w for w in weights)) if total > 0 else 0.0
    return weights, n_eff


# ---------------------------------------------------------------- forecast

def persistence_quantiles(v1, hour):
    """The house baseline's row for one hour (the fallback when evidence fails)."""
    return [v1 * math.exp(z * BASE_SIGMA * math.sqrt(hour - 1)) for z in Z]


def forecast_case(case):
    """{hour: [q05, q25, q50, q75, q95]} for the case's forecast hours 2..24."""
    day_start = parse_time(case.get("day_start"))
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    hours = [row["hour"] for row in case.get("forecast") or []]
    if day_start is None or first is None:
        return {}
    v1 = max(1.0, float(first.get("viewers") or 0))

    # The target's checkpoint view: its own history (never past hour 1) + its prose.
    series = hourly_viewers(case.get("history_hourly") or case.get("history"))
    target_feats = pre_release_features(series, day_start, v1)
    target_class = unlock_class(case.get("notes"))

    pool = []
    for comp in case.get("comparables") or []:
        built = comparable_curve(comp)
        if built is not None:
            pool.append(built)
    if not pool:
        return {h: persistence_quantiles(v1, h) for h in hours}

    weights, n_eff = similarity_weights(target_feats, target_class, pool)
    if n_eff <= 0:
        return {h: persistence_quantiles(v1, h) for h in hours}

    # Shape: weighted median log-ratio per hour, shrunk toward persistence (0).
    shrink = n_eff / (n_eff + SHAPE_SHRINK_K)
    shape = {}
    for h in range(2, 25):
        pairs = [(curve[h], weights[i]) for i, (_, curve, _) in enumerate(pool) if h in curve]
        if pairs:
            shape[h] = weighted_quantile(pairs, 0.5) * shrink

    # Residuals around the (unshrunk) median shape, for the spread.
    raw_shape = {}
    for h in range(2, 25):
        pairs = [(curve[h], weights[i]) for i, (_, curve, _) in enumerate(pool) if h in curve]
        if pairs:
            raw_shape[h] = weighted_quantile(pairs, 0.5)
    residuals = {}
    for i, (_, curve, _) in enumerate(pool):
        for h, lv in curve.items():
            if h in raw_shape:
                residuals.setdefault(h, []).append((lv - raw_shape[h], weights[i]))

    out = {}
    for h in hours:
        if h not in shape:
            out[h] = persistence_quantiles(v1, h)
            continue
        pooled = []
        for hh in (h - 1, h, h + 1):
            pooled.extend(residuals.get(hh, []))
        if not pooled:
            out[h] = [v1 * math.exp(shape[h])] * 5
            continue
        wsum = sum(w for _, w in pooled)
        mean = sum(v * w for v, w in pooled) / wsum
        var = sum(w * (v - mean) ** 2 for v, w in pooled) / wsum
        sigma = math.sqrt(var) if var > 0 else 0.0
        qs = []
        for tau, z in zip(LEVELS, Z):
            emp = weighted_quantile(pooled, tau)
            rq = (1 - RESID_NORMAL_BLEND) * emp + RESID_NORMAL_BLEND * (mean + z * sigma)
            qs.append(v1 * math.exp(shape[h] + rq))
        qs.sort()
        out[h] = [min(max(q, 1.0), 1e9) for q in qs]
    return out
