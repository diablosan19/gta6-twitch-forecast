# What the case files actually contain (explored 2026-11-18, from p00–p03)

## The case

- One JSON object, schema `makefun/twitch-ccu-case/v1`: `id`, `game {name, twitch_id}`,
  `day_start` (00:00 UTC of release day), `checkpoint` (day_start + 1 h), `levels`
  [0.05, 0.25, 0.5, 0.75, 0.95], `known` (one row: hour 1's mean viewers/channels over
  [00:00Z, 01:00Z)), `forecast` (23 rows, hours 2..24 with from/until), `history`,
  `history_hourly`, `streams`, `categories_hourly`, `comparables` (38), `notes` (prose).
- `streams` and `categories_hourly` are **null in all four practice cases** — dead fields
  as far as practice shows; the model must not depend on them.
- `history` and `history_hourly` are the **same series** in two spellings
  (`{at, viewers, channels}` vs `{from, viewers, channels, reads}`). Points are hourly
  SullyGnome category averages: a point at `t` is the mean concurrent viewers over
  [t, t+1h). Early points are sparse/irregular (gaps up to ~23 h, tiny leak-level
  counts); the last ~48 h are dense, one point per hour. The series ends exactly at
  hour 1 of release day (its last point equals `known`). It does **not** contain the
  target's hours 2..24 — a practice case's own truth is nowhere in its file.
- `notes` is prose with the release context: platforms, unlock pattern and timing
  (e.g. "Rolling midnight local … US Eastern = 04:00Z; NZ ~12:00Z the day before"),
  preload/early-access facts, and the data-provenance paragraph.

## The comparables (identical 38 in every practice case)

Each comparable: `{name, day_start, platforms, unlock (prose), source, hourly}` where
`hourly` is the same SullyGnome-style series as the target's history, spanning from
~14 days before its release day to days after (117–632 points).

- **37 of 38 are real launches with a complete release day**: an hour-1 point at
  `day_start` and all 24 hourly points of release day present, plus 19–24 points in
  the 24 h before `day_start`. These are the training curves: each gives the full
  shape `v(h)/v(1)`, h = 1..24, and — computed from its own pre-release points with
  exactly the same code as the target's — the checkpoint features below.
- **1 of 38 is not a launch**: "Grand Theft Auto VI category before release" — the
  final target's own category history from its 2026-08-27 premiere to 2026-11-17
  (sparse, ~12 h sampling; max 1.42M viewers at the premiere). Its `day_start` is the
  premiere date, it has no release-day curve, and it must be excluded from the pool
  by rule (no hour-1 point on a release day), never by name. Its `unlock` text does
  state the final case's facts: **GTA VI releases 2026-11-19, rolling midnight local,
  NZ first at 2026-11-18T11:00Z**.
- The `unlock` prose is uneven: some precise ("Single global unlock … 2024-08-20T02:00Z"),
  many "unverified" with the pattern only implied. Text is a soft prior at best;
  the curves' own behaviour is the reliable signal.

## What the curves look like (the fact the model is built on)

Release-day shape is governed by **when the world unlocks relative to 00:00 UTC**:

- **Rolling midnight-local** (all four practice targets; most console launches):
  NZ/AU unlock ~11:00–13:00Z on day −1, so by hour 1 a real audience exists, but
  hour 1 (00:00–01:00Z) is a *trough* — EU asleep, US not yet unlocked (US Eastern
  unlock 04:00–05:00Z). The day's peak lands at hours 16–23 (EU prime + US afternoon),
  at 1.3×–12× hour 1. All four practice targets show the signature in their own
  history: day −1's evening peak is 1.6×–2.8× hour 1, and the 24 h pre-release mean
  is 0.63×–0.91× hour 1.
- **Single global unlock during the UTC day** (Silksong 14:00Z, Wukong 02:00Z,
  Baldur's Gate 3, Battlefield 6, …): hour 1 is pre-unlock noise (v1 as low as 164),
  and later hours reach 60×–2000× hour 1. These are instantly recognisable by a tiny
  v1 relative to their own scale — and they are the *wrong* shape family for a
  rolling launch, so the pool must be weighted, not averaged blindly.
- **Already live at hour 1** (global unlock ≤ 00:00Z, e.g. Cyberpunk; or multi-day
  early access, e.g. Starfield, Diablo IV): hour 1 is at/near the day's peak and the
  shape decays (v24/v1 ≈ 0.55–0.96).

Checkpoint-knowable features (computable identically for target and comparables):
`v1` (hour-1 viewers), pre-release peak ratio `max v[t], t in [day_start−24h, day_start) / v1`,
pre-release mean ratio over the same window, and the unlock text. Between them they
separate the three families well enough to weight the pool: the practice targets sit
at v1 = 23k–270k, pre-peak ratio 1.6–2.8, pre-mean ratio 0.63–0.91 — squarely in the
rolling family and far from both the tiny-v1 global-unlock cluster and the
pre-mean ≈ 0.03–0.35 already-decayed cluster (Marvel Rivals 0.028, Nightreign 0.114).

## Scoring-relevant facts

- Score is pinball loss on **log** viewers, hours 2..24 × 5 levels, against the
  hour's actual mean. Modelling in log space is therefore exact, not an approximation.
- The starter baseline is persistence: median = v1 at every hour, spread
  `0.15·sqrt(h−1)` in log space, symmetric normal quantiles. It wastes everything the
  case file knows — the shape above is worth a great deal against it, especially at
  hours 16–24 where rolling launches peak far above hour 1.
