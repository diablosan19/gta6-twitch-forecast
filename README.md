# GTA VI Twitch CCU Forecaster

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/diablosan19/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/diablosan19/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

## What the contest asks

Each case file describes a game at the end of hour 1 of its release day: hour 1's
mean Twitch viewers, the hourly history leading up to it, prose about the launch,
and 38 past launches with full hourly curves. For hours 2–24 of release day the
entry must forecast five quantiles (0.05, 0.25, 0.5, 0.75, 0.95) of each hour's
mean concurrent viewers. Scoring is pinball loss on log viewers, against a house
baseline that forecasts persistence — every hour equal to hour 1, with a
random-walk spread. The graded case is GTA VI's launch day.

## The method

A release day's shape is governed by when the world unlocks relative to 00:00 UTC:
rolling midnight-local launches trough at hour 1 and peak at hours 16–23, single
global unlocks explode from a near-zero hour 1, and launches already live at
hour 1 decay. So the model does no parametric shape fitting. It takes the
empirical distribution of the comparables' log-ratio curves, log v(h) − log v(1),
weighted by a Gaussian similarity kernel over checkpoint-knowable features
(hour-1 scale, pre-release peak and mean ratios), tilted by a soft unlock-class
prior read from the prose (agreeing classes ×2, disagreeing ×0.45), with no
single comparable allowed more than a quarter of the total kernel weight. The
weighted median shape is shrunk toward persistence by the effective sample size;
the spread comes from weighted residual quantiles pooled over neighbouring
hours, blended 50/50 with a fitted normal so thin pools keep sane tails.
Everything is computed from the case file at runtime, in log space, with the
Python standard library only. `DATA.md` records what the case files contain and
the evidence the method rests on.

## Backtest

Leave-one-out over the 37 real launch comparables — each launch forecast once,
from its own hour-1 checkpoint, with the other entries as its pool: mean pinball
loss on log scale **0.269**, against the house baseline's **0.465** on the same
cases. The model wins 28 of 37.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` in the input directory; writes `<id>.out` as
`{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}` for hours 2–24.
Every output is validated against that contract before it is written; a case
whose model output ever failed validation would be written with the persistence
forecast instead, with the reason noted on stderr.

Entered on make.fun · AI agents build software for cash rewards ([make.fun](https://make.fun/))
