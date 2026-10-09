"""Compare models on your samples.

    python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf Qwen3-4B-Q5_K_M.gguf

Bare filenames are looked up in the models folder. For clean RAM numbers, run one model per
command (memory from a previous model may not be fully returned to the OS).
"""
import argparse
import gc
import json
import time
from datetime import datetime
from pathlib import Path

from core.config import MODELS_DIR
from core.extraction import PRENATAL_FIELDS, extract
from evals.scoring import score_sample, summarize

HERE = Path(__file__).resolve().parent


def load_samples(path) -> list:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [
        json.loads(line)
        for line in lines
        if line.strip() and not line.strip().startswith(("//", "#"))
    ]


def evaluate(llm, samples, fields=PRENATAL_FIELDS, fewshot=None, glossary=None, on_sample=None) -> dict:
    results = []
    for s in samples:
        start = time.time()
        out = extract(llm, s["note"], fields, fewshot, glossary)
        seconds = time.time() - start
        correct = score_sample(s["expected"], out["fields"], fields)
        results.append({"id": s["id"], "note": s["note"], "expected": s["expected"],
                        "got": out["fields"], "ok": out["ok"], "problems": out["problems"],
                        "correct": correct, "seconds": seconds})
        if on_sample:
            on_sample(results[-1])
    return {"summary": summarize(results, fields), "results": results}


def _rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except ImportError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--samples", default=str(HERE / "samples.jsonl"))
    ap.add_argument("--n-ctx", type=int, default=2048)
    args = ap.parse_args()

    from core.inference import LlamaCppLLM  # imported here so tests don't need llama-cpp-python
    samples = load_samples(args.samples)
    report = {}
    for name in args.models:
        path = Path(name)
        if not path.exists():
            path = MODELS_DIR / name
        print(f"\n=== {path.name} ({len(samples)} samples) ===")
        llm = LlamaCppLLM(str(path), n_ctx=args.n_ctx)
        peak = [0.0]

        def progress(r):
            peak[0] = max(peak[0], _rss_mb() or 0)
            print(f"  {r['id']}: {sum(r['correct'].values())}/{len(r['correct'])} fields right, {r['seconds']:.1f}s")

        out = evaluate(llm, samples, on_sample=progress)
        out["summary"]["peak_rss_mb"] = peak[0] or None
        report[path.name] = out
        del llm
        gc.collect()

    print("\n=== SUMMARY ===")
    print(f"{'model':32} {'fields':>7} {'exact':>6} {'parse_fail':>10} {'avg s':>6} {'RAM MB':>7}")
    for name, out in report.items():
        s = out["summary"]
        ram = f"{s['peak_rss_mb']:.0f}" if s["peak_rss_mb"] else "n/a"
        print(f"{name:32} {s['overall']:7.0%} {s['exact_match']:6.0%} {s['parse_fail']:10.0%} "
              f"{s['avg_seconds']:6.1f} {ram:>7}")
    print("\nMISSES (expected vs got):")
    for name, out in report.items():
        for r in out["results"]:
            for f, ok in r["correct"].items():
                if not ok:
                    print(f"  [{name}] {r['id']} {f}: expected {r['expected'].get(f)!r}, got {r['got'][f]!r}")

    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    out_path = results_dir / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
