"""Dev-only helper: sweep generator knobs and report the demo-story metrics."""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
GEN = str(ROOT / "data" / "generate_data.py")


def measure():
    for m in [m for m in sys.modules if m.startswith("app.")]:
        del sys.modules[m]
    from app.services import data_loader
    data_loader.reset_cache()
    from app.services.transaction_analytics import build_context, metrics_payload
    ctx = build_context()
    m = metrics_payload(ctx)
    worst = sorted(m["day_of_week"]["weekday_comparison"], key=lambda d: d["change_percent"])[0]
    return {
        "evening": m["time_of_day"]["evening_change_percent"],
        "repeat": m["customers"]["repeat_transaction_change"],
        "worst_day": worst["day"],
        "worst_pct": worst["change_percent"],
        "weekend": m["day_of_week"]["weekend_change_percent"],
        "aov_base": ctx.avg_ticket_vs_baseline,
        "rev_wow": m["revenue"]["growth_percent"],
        "rev_base": m["revenue"]["vs_baseline_percent"],
        "txn_wow": m["transactions"]["growth_percent"],
    }


def run(knobs):
    env = dict(os.environ)
    for k, v in knobs.items():
        env[f"PBH_{k.upper()}"] = str(v)
    subprocess.run([PY, GEN], env=env, check=True, capture_output=True, cwd=str(ROOT))
    return measure()


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        knobs = json.loads(spec)
        print(json.dumps({**knobs, **run(knobs)}))
