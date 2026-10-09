"""Pure scoring logic (no model needed, so it can be unit-tested)."""


def values_match(expected, got, tol: float = 0.05) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got
    return abs(float(expected) - float(got)) <= tol


def score_sample(expected: dict, got: dict, fields) -> dict:
    """Per-field correctness. A field missing from `expected` means 'not mentioned' = None."""
    return {f: values_match(expected.get(f), got.get(f)) for f in fields}


def summarize(results: list, fields) -> dict:
    n = len(results) or 1
    per_field = {f: sum(r["correct"][f] for r in results) / n for f in fields}
    return {
        "samples": len(results),
        "field_accuracy": per_field,
        "overall": sum(per_field.values()) / len(per_field),
        "exact_match": sum(all(r["correct"].values()) for r in results) / n,
        "parse_fail": sum(not r["ok"] for r in results) / n,
        "avg_seconds": sum(r["seconds"] for r in results) / n,
    }
