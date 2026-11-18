"""gta6-twitch-ccu-forecast-01 entry point: case I/O around model.py's forecaster.

The forecasting itself lives in model.py (comparable-shape quantile regression in
log space; method and evidence in DATA.md and model.py's docstring). This file owns
everything around it:

  discovery   every <id>.in in the input directory, processed in name order so two
              runs write the same bytes;
  parsing     each file read as JSON with errors that name the file and the problem
              (a file that is not a case at all aborts the run loudly — there is no
              honest forecast to write for it);
  validation  the model's rows are checked against the output contract before
              anything is written: exactly 23 rows for hours 2..24, five finite
              non-decreasing quantiles per row, each in (0, 1e9], the encoded
              document at most 65,536 bytes;
  fallback    a case whose model output fails validation (or whose model call
              raises) is written with the house persistence forecast instead —
              every hour equals hour 1's viewers with the baseline's random-walk
              spread — and a note naming the reason goes to stderr. A pathological
              case therefore scores like the baseline rather than producing an
              invalid file.

Contract (unchanged from the starter): read every <id>.in in the input directory;
write <id>.out as {"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}.
Standard library only; the grader runs `python3 -P -s /bot/main.py`, so the
sys.path line below puts this file's directory first and `import model` finds the
model.py shipped beside it.

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
# The forecast hours, in output order: 23 rows, hours 2..24.
HOURS = list(range(2, 25))
# Output bounds from the contract: quantiles in (0, MAX_Q], file at most this big.
MAX_Q = 1e9
MAX_OUTPUT_BYTES = 65_536


class CaseError(Exception):
    """A case file that cannot be read as a case at all.

    Distinct from a model output we merely refuse to trust: that falls back to
    persistence (see forecast_document); this aborts the run, because without a
    parseable case or an hour-1 anchor there is nothing honest to write.
    """


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


# ------------------------------------------------------------------ reading

def discover_cases(input_dir: Path) -> list[Path]:
    """Every case file in the input directory, in name order (deterministic runs)."""
    return sorted(input_dir.glob("*.in"))


def read_case(path: Path) -> dict:
    """One case file parsed as JSON; a CaseError names the file and the problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaseError(f"{path.name}: cannot read the file ({exc})") from exc
    try:
        case = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CaseError(f"{path.name}: not valid JSON ({exc})") from exc
    if not isinstance(case, dict):
        raise CaseError(f"{path.name}: top level is a {type(case).__name__}, not a JSON object")
    return case


def hour_one_viewers(case: dict, name: str) -> float:
    """v1, hour 1's viewers: the anchor every forecast in this entry hangs from."""
    for row in case.get("known") or []:
        if isinstance(row, dict) and row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and not isinstance(viewers, bool) \
                    and math.isfinite(viewers) and viewers > 0:
                return float(viewers)
            break
    raise CaseError(f"{name}: no usable hour-1 viewers in 'known'")


# ------------------------------------------------------------------ checking

def validate_rows(rows) -> str | None:
    """None when rows meet the output contract, else a short reason they do not.

    The contract per row set: exactly 23 rows for hours 2..24 in order, each with
    five finite non-decreasing quantiles, every one above 0 and at most 1e9.
    """
    if not isinstance(rows, list) or len(rows) != len(HOURS):
        return f"{len(rows) if isinstance(rows, list) else 'no'} rows, not {len(HOURS)}"
    for row, hour in zip(rows, HOURS):
        if not isinstance(row, dict) or row.get("hour") != hour:
            seen = row.get("hour") if isinstance(row, dict) else row
            return f"a row's hour is {seen!r}, expected {hour}"
        qs = row.get("q")
        if not isinstance(qs, list) or len(qs) != len(LEVELS):
            return f"hour {hour}: q is not a list of {len(LEVELS)} quantiles"
        previous = None
        for q in qs:
            if isinstance(q, bool) or not isinstance(q, (int, float)):
                return f"hour {hour}: quantile {q!r} is not a number"
            if not math.isfinite(q):
                return f"hour {hour}: quantile {q!r} is not finite"
            if q <= 0 or q > MAX_Q:
                return f"hour {hour}: quantile {q!r} is outside (0, 1e9]"
            if previous is not None and q < previous:
                return f"hour {hour}: quantiles decrease at {q!r}"
            previous = q
    return None


def encode_document(document: dict) -> bytes:
    """The exact bytes of an output file: compact JSON plus a trailing newline."""
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


# ------------------------------------------------------------------ forecasting

def model_rows(case: dict) -> tuple[list | None, str | None]:
    """(rows, None) built from the model, or (None, reason) when unusable.

    Any failure — the call raising, a missing hour, a non-numeric quantile, a row
    set that fails validation, an oversized encoding — is reported as a reason,
    never propagated: the caller turns it into the persistence fallback.
    """
    try:
        by_hour = model.forecast_case(case)
    except Exception as exc:  # a model failure is a bad forecast, not a crash
        return None, f"model raised {type(exc).__name__}: {exc}"
    if not isinstance(by_hour, dict):
        return None, "model did not return a mapping of hours"
    rows = []
    for hour in HOURS:
        qs = by_hour.get(hour)
        if not isinstance(qs, (list, tuple)) or len(qs) != len(LEVELS):
            return None, f"hour {hour}: model gave no {len(LEVELS)}-quantile row"
        try:
            rows.append({"hour": hour, "q": [round2(float(q)) for q in qs]})
        except (TypeError, ValueError, OverflowError):
            return None, f"hour {hour}: model gave a non-numeric quantile"
    problem = validate_rows(rows)
    if problem is not None:
        return None, problem
    if len(encode_document({"hours": rows})) > MAX_OUTPUT_BYTES:
        return None, f"encoded output exceeds {MAX_OUTPUT_BYTES} bytes"
    return rows, None


def persistence_rows(v1: float) -> list:
    """The house baseline's rows for anchor v1, clamped inside the contract.

    model.persistence_quantiles supplies the baseline law (median = v1, spread
    0.15*sqrt(h-1) in log space). Rounding and clamping here are monotone, so the
    rows stay non-decreasing and inside (0, 1e9] by construction.
    """
    rows = []
    for hour in HOURS:
        qs = [min(max(round2(float(q)), 0.01), MAX_Q) for q in model.persistence_quantiles(v1, hour)]
        rows.append({"hour": hour, "q": qs})
    return rows


def forecast_document(case: dict, name: str) -> dict:
    """The {"hours": [...]} document for one case, validated before it is written.

    The model's rows are used only when they pass validation; otherwise the
    persistence fallback is written instead and the reason is noted on stderr.
    """
    if case.get("levels") != LEVELS:
        raise CaseError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    rows, problem = model_rows(case)
    if problem is not None:
        print(f"{name}: model forecast rejected ({problem}); writing persistence fallback", file=sys.stderr)
        rows = persistence_rows(hour_one_viewers(case, name))
        problem = validate_rows(rows)
        if problem is not None:  # unreachable by construction; never write invalid output
            raise CaseError(f"{name}: persistence fallback is invalid ({problem})")
    return {"hours": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in discover_cases(INPUT_DIR):
        try:
            document = forecast_document(read_case(path), path.name)
        except CaseError as exc:
            print(f"main: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        (OUTPUT_DIR / f"{path.stem}.out").write_bytes(encode_document(document))


if __name__ == "__main__":
    main()
