"""gta6-twitch-ccu-forecast-01 entry: comparable-shape quantile regression (see model.py).

The house baseline forecasts persistence: every hour equals hour 1's viewers, with a
random-walk spread. This entry instead reads the case's 38 comparable launches, takes
the empirical distribution of their release-day log-ratio curves log v(h) - log v(1),
weighted by checkpoint-knowable similarity to the target (hour-1 scale, pre-release
peak/mean ratios, unlock pattern), and reports that distribution's quantiles around a
similarity-weighted median shape. All in log space, because the score is pinball loss
on log viewers. Method and evidence: DATA.md and model.py.

Contract (unchanged from the starter): read every <id>.in in the input directory;
write <id>.out as {"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]} with
exactly the 23 rows for hours 2..24, five finite non-decreasing quantiles per row,
each above 0 and at most 1e9, at most 65,536 bytes. Standard library only; the grader
runs `python3 -P -s /bot/main.py`, so the sys.path line below puts this file's
directory first and `import model` finds the model.py shipped beside it.

Outside the grader's container, MAKEFUN_INPUT_DIR and MAKEFUN_OUTPUT_DIR stand in
for /input and /output:
    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so `import model` finds a model.py shipped beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import model

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's Math.round(x * 100) / 100 rounds it.

    A whole number comes back as an int, so json.dumps writes 1240 where JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    by_hour = model.forecast_case(case)
    rows = []
    for row in case["forecast"]:
        qs = by_hour[row["hour"]]
        rows.append({"hour": row["hour"], "q": [round2(q) for q in qs]})
    return {"hours": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
