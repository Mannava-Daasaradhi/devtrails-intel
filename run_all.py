"""
run_all.py — DEVTrails Intel Master Orchestrator
Runs the full pipeline in sequence:
  Phase 1: 01_search_repos.py    (~9 min)
  Phase 2: 02_clone_repos.py     (~20–40 min)
  Phase 3: 03_review_repos.py    (~7–8 hours — run overnight)
  Phase 4: 04_synthesize.py      (~1–2 hours)

Usage:
    python run_all.py                        # full run
    python run_all.py --from-phase 3         # resume from a specific phase
    python run_all.py --phases 1 2           # run only specific phases
    python run_all.py --dry-run              # print what would run, don't execute
    python run_all.py --validate             # run Phase 3 --validate-only then stop
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------

PHASES = [
    {
        "id": 1,
        "name": "GitHub Repository Discovery",
        "script": "src/01_search_repos.py",
        "estimate": "~9 minutes",
        "gate": "repos_manifest.json with ≥265 entries",
    },
    {
        "id": 2,
        "name": "Repository Cloning",
        "script": "src/02_clone_repos.py",
        "estimate": "~20–40 minutes",
        "gate": "≥220 repos cloned in repos/",
    },
    {
        "id": 3,
        "name": "Deep Code Review",
        "script": "src/03_review_repos.py",
        "estimate": "~7–8 hours (run overnight)",
        "gate": "≥90% of reviews/*.md files pass validation",
    },
    {
        "id": 4,
        "name": "Knowledge Synthesis",
        "script": "src/04_synthesize.py",
        "estimate": "~1–2 hours",
        "gate": "knowledge/MASTER_PATTERNS.md, GAPS.md, YOUR_FEATURE_PLAN.md present",
    },
]

VALIDATE_ONLY_ARGS = {3: ["--validate-only"]}  # Extra args per phase when --validate is set

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def make_log_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"run_{ts}.log"


class Tee:
    """Write to both stdout and a log file simultaneously."""

    def __init__(self, log_path: Path):
        self.log_file = log_path.open("a", encoding="utf-8", buffering=1)
        self.stdout = sys.stdout

    def write(self, data):
        self.stdout.write(data)
        self.log_file.write(data)

    def flush(self):
        self.stdout.flush()
        self.log_file.flush()

    def isatty(self):
        return self.stdout.isatty()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hr(char: str = "─", width: int = 60) -> str:
    return char * width


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_phase(phase: dict, extra_args: list[str] | None = None, dry_run: bool = False) -> bool:
    """
    Run a single phase script as a subprocess.
    Returns True if the script exited with code 0, False otherwise.
    """
    script = phase["script"]
    cmd = [sys.executable, script] + (extra_args or [])
    label = f"Phase {phase['id']} — {phase['name']}"

    print(f"\n{hr()}")
    print(f"[{ts()}] Starting: {label}")
    print(f"           Script  : {script}")
    print(f"           Estimate: {phase['estimate']}")
    print(f"           Gate    : {phase['gate']}")
    if extra_args:
        print(f"           Args    : {' '.join(extra_args)}")
    print(hr())

    if dry_run:
        print(f"  [DRY RUN] Would run: {' '.join(cmd)}")
        return True

    if not Path(script).exists():
        print(f"  [ERROR] Script not found: {script}")
        print(f"          Make sure you are running from the devtrails-intel/ root directory.")
        return False

    start = time.time()
    try:
        result = subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted by user. Exiting.")
        sys.exit(130)

    elapsed = time.time() - start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    if result.returncode == 0:
        print(f"\n[{ts()}] ✓ Phase {phase['id']} completed in {minutes}m {seconds}s")
        return True
    else:
        print(
            f"\n[{ts()}] ✗ Phase {phase['id']} FAILED "
            f"(exit code {result.returncode}) after {minutes}m {seconds}s"
        )
        return False


def print_plan(phases_to_run: list[dict], dry_run: bool):
    print(hr("═"))
    print("  DEVTrails Intel — Full Pipeline")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Dry run  : {'YES — no scripts will be executed' if dry_run else 'NO'}")
    print(f"  Phases   : {', '.join(str(p['id']) for p in phases_to_run)}")
    print(hr("═"))
    for p in phases_to_run:
        print(f"  Phase {p['id']}: {p['name']:<30}  estimate: {p['estimate']}")
    print(hr("═"))


# ---------------------------------------------------------------------------
# Quality gate checks (simple file-existence checks before each phase)
# ---------------------------------------------------------------------------

def check_gate_before(phase_id: int) -> tuple[bool, str]:
    """
    Lightweight pre-flight check before running a phase.
    Returns (ok, message).
    """
    if phase_id == 2:
        manifest = Path("repos_manifest.json")
        if not manifest.exists():
            return False, "repos_manifest.json not found — run Phase 1 first"
    if phase_id == 3:
        manifest = Path("repos_manifest.json")
        if not manifest.exists():
            return False, "repos_manifest.json not found — run Phase 1 first"
        repos = Path("repos")
        if not repos.exists() or not any(repos.iterdir()):
            return False, "repos/ directory is empty — run Phase 2 first"
    if phase_id == 4:
        reviews = Path("reviews")
        if not reviews.exists() or not any(reviews.glob("*.md")):
            return False, "reviews/ has no .md files — run Phase 3 first"
    return True, "OK"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="DEVTrails Intel — Full Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_all.py                   Full run (phases 1-4)
  python run_all.py --from-phase 3    Resume from Phase 3
  python run_all.py --phases 1 2      Run only phases 1 and 2
  python run_all.py --dry-run         Preview without executing
  python run_all.py --validate        Run Phase 3 --validate-only then stop
  python run_all.py --dashboard       Run the dashboard after each phase
        """,
    )
    parser.add_argument(
        "--from-phase",
        type=int,
        metavar="N",
        choices=[1, 2, 3, 4],
        help="Start from phase N (skipping earlier phases)",
    )
    parser.add_argument(
        "--phases",
        type=int,
        nargs="+",
        metavar="N",
        choices=[1, 2, 3, 4],
        help="Run only the listed phases (e.g. --phases 1 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run but do not execute any scripts",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run Phase 3 in --validate-only mode and stop",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Run 05_dashboard.py after each completed phase",
    )
    parser.add_argument(
        "--skip-gate-check",
        action="store_true",
        help="Skip the pre-flight gate check before each phase",
    )
    args = parser.parse_args()

    # ── Set up logging ──────────────────────────────────────────────
    log_path = make_log_path()
    sys.stdout = Tee(log_path)
    print(f"[LOG] Writing to {log_path}")

    # ── Determine which phases to run ───────────────────────────────
    if args.validate:
        phases_to_run = [p for p in PHASES if p["id"] == 3]
        extra_args_override = {3: ["--validate-only"]}
    elif args.phases:
        phases_to_run = [p for p in PHASES if p["id"] in args.phases]
        extra_args_override = {}
    elif args.from_phase:
        phases_to_run = [p for p in PHASES if p["id"] >= args.from_phase]
        extra_args_override = {}
    else:
        phases_to_run = list(PHASES)
        extra_args_override = {}

    if not phases_to_run:
        print("[ERROR] No phases selected.")
        sys.exit(1)

    print_plan(phases_to_run, args.dry_run)

    # ── Run phases ──────────────────────────────────────────────────
    overall_start = time.time()
    results: dict[int, bool] = {}

    for phase in phases_to_run:
        # Pre-flight gate check
        if not args.skip_gate_check and not args.dry_run:
            ok, msg = check_gate_before(phase["id"])
            if not ok:
                print(f"\n[{ts()}] ✗ Gate check failed before Phase {phase['id']}: {msg}")
                print(f"         Use --skip-gate-check to bypass, or fix the issue first.")
                sys.exit(1)

        extra_args = extra_args_override.get(phase["id"])
        success = run_phase(phase, extra_args=extra_args, dry_run=args.dry_run)
        results[phase["id"]] = success

        # Show dashboard after each phase if requested
        if args.dashboard and not args.dry_run and Path("repos_manifest.json").exists():
            print(f"\n[{ts()}] Dashboard snapshot:")
            subprocess.run(
                [sys.executable, "src/05_dashboard.py", "--no-color"],
                check=False,
            )

        # Stop on failure
        if not success and not args.dry_run:
            print(
                f"\n[{ts()}] Pipeline halted at Phase {phase['id']}. "
                f"Fix the error and re-run with --from-phase {phase['id']}."
            )
            break

    # ── Final summary ───────────────────────────────────────────────
    total_elapsed = time.time() - overall_start
    total_min = int(total_elapsed // 60)
    total_sec = int(total_elapsed % 60)

    print(f"\n{hr('═')}")
    print(f"  Pipeline Summary  ({total_min}m {total_sec}s total)")
    print(hr("═"))
    for phase in phases_to_run:
        pid = phase["id"]
        if pid not in results:
            status = "  SKIPPED"
        elif results[pid]:
            status = "✓  OK     "
        else:
            status = "✗  FAILED "
        print(f"  Phase {pid} [{status}]  {phase['name']}")
    print(hr("═"))
    print(f"  Log saved to: {log_path}")
    print(hr("═"))

    # Exit code: 1 if any phase failed
    if any(not v for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
