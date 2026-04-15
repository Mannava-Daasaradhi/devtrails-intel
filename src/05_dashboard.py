"""
src/05_dashboard.py — Pipeline Progress Dashboard

BUG 5 FIX: Gate 2→3 always showed 0 repos cloned because the dashboard checked for
clone_status == "complete", but Phase 2 (02_clone_repos.py) writes "success", "empty",
or "sparse" — never "complete". Added CLONE_COMPLETE_STATUSES set mapping Phase 2's
actual status values to the "cloned successfully" concept.

Usage:
    python src/05_dashboard.py
    python src/05_dashboard.py --verbose
    python src/05_dashboard.py --failed-only
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

MANIFEST_PATH = Path("repos_manifest.json")
REVIEWS_DIR = Path("reviews")
KNOWLEDGE_DIR = Path("knowledge")

# BUG 5 FIX: Phase 2 writes these three statuses — NOT "complete".
# The dashboard must check for all three when computing the cloned count.
CLONE_COMPLETE_STATUSES = {"success", "empty", "sparse"}

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"


def color(text: str, code: str, use_color: bool = True) -> str:
    return f"{code}{text}{RESET}" if use_color else text


def bar(count: int, total: int, width: int = 30) -> str:
    filled = int(width * count / max(total, 1))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def pct(count: int, total: int) -> str:
    return f"{100 * count / max(total, 1):.0f}%"


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        print(f"[ERROR] {MANIFEST_PATH} not found. Run Phase 1 first.")
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def check_knowledge_files() -> dict:
    files = ["MASTER_PATTERNS.md", "GAPS.md", "YOUR_FEATURE_PLAN.md", "freq_cache.json"]
    return {f: (KNOWLEDGE_DIR / f).exists() for f in files}


def print_dashboard(manifest: list[dict], verbose: bool, failed_only: bool, use_color: bool):
    total = len(manifest)
    if total == 0:
        print("Manifest is empty.")
        return

    clone_statuses = Counter(t.get("clone_status", "unknown") for t in manifest)
    review_statuses = Counter(t.get("review_status", "unknown") for t in manifest)
    confidences = Counter(t.get("confidence", "unknown") for t in manifest)
    knowledge_files = check_knowledge_files()

    reviews_on_disk = len(list(REVIEWS_DIR.glob("*.md"))) if REVIEWS_DIR.exists() else 0

    # BUG 5 FIX: Count all Phase 2 success statuses, not just "complete"
    cloned_count = sum(
        1 for t in manifest
        if t.get("clone_status") in CLONE_COMPLETE_STATUSES
    )

    sep = "─" * 54

    if not failed_only:
        print(color(sep, BOLD, use_color))
        print(color("  DEVTrails Intel — Pipeline Dashboard", BOLD + CYAN, use_color))
        print(color(f"  Total teams in manifest: {total}", BOLD, use_color))
        print(color(sep, BOLD, use_color))

        # ── Repo Discovery ──────────────────────────────────────────
        print(color("\n  REPO DISCOVERY", BOLD, use_color))
        for status in ["HIGH", "LOW", "NOT_FOUND", "unknown"]:
            count = confidences.get(status, 0)
            if count == 0:
                continue
            label_color = GREEN if status == "HIGH" else (YELLOW if status == "LOW" else RED)
            print(
                color(f"  {status:<12}", label_color, use_color)
                + f" {bar(count, total)}  {count:>4} / {total}  ({pct(count, total)})"
            )
            if verbose and status in ("LOW", "NOT_FOUND"):
                for t in manifest:
                    if t.get("confidence") == status:
                        score = t.get("score", "?")
                        print(color(f"         • {t['team_name']} (score {score})", DIM, use_color))

        # ── Clone Status ─────────────────────────────────────────────
        print(color("\n  CLONE STATUS", BOLD, use_color))
        # Show Phase 2 actual statuses
        for status in ["success", "empty", "sparse", "failed", "unknown"]:
            count = clone_statuses.get(status, 0)
            if count == 0:
                continue
            label_color = GREEN if status in CLONE_COMPLETE_STATUSES else (RED if status == "failed" else YELLOW)
            print(
                color(f"  {status:<12}", label_color, use_color)
                + f" {bar(count, total)}  {count:>4} / {total}  ({pct(count, total)})"
            )
        print(
            color(f"  {'TOTAL CLONED':<12}", GREEN, use_color)
            + f" {bar(cloned_count, total)}  {cloned_count:>4} / {total}  ({pct(cloned_count, total)})"
            + color("  (success+empty+sparse)", DIM, use_color)
        )

        # ── Review Status ─────────────────────────────────────────────
        complete_count = review_statuses.get("complete", 0)
        print(color("\n  REVIEW STATUS", BOLD, use_color))
        for status in ["complete", "pending", "failed", "unknown"]:
            count = review_statuses.get(status, 0)
            if count == 0:
                continue
            label_color = GREEN if status == "complete" else (RED if status == "failed" else YELLOW)
            print(
                color(f"  {status:<12}", label_color, use_color)
                + f" {bar(count, total)}  {count:>4} / {total}  ({pct(count, total)})"
            )

        manifest_complete = review_statuses.get("complete", 0)
        disk_match = "✓" if reviews_on_disk == manifest_complete else "⚠"
        disk_color = GREEN if reviews_on_disk == manifest_complete else YELLOW
        print(
            color(f"\n  Reviews on disk : {reviews_on_disk}", disk_color, use_color)
            + f"  {disk_match} "
            + color(f"(manifest says: {manifest_complete})", DIM, use_color)
        )

        # ── Knowledge Files ───────────────────────────────────────────
        print(color("\n  KNOWLEDGE FILES", BOLD, use_color))
        for fname, exists in knowledge_files.items():
            icon = color("✓", GREEN, use_color) if exists else color("✗", RED, use_color)
            print(f"    {icon}  {fname}")

        # ── Quality Gates ─────────────────────────────────────────────
        print(color("\n  QUALITY GATES", BOLD, use_color))

        def gate(label: str, passed: bool, detail: str = ""):
            mark = color("PASS", GREEN, use_color) if passed else color("FAIL", RED, use_color)
            print(f"    [{mark}]  {label}" + (f"  {color(detail, DIM, use_color)}" if detail else ""))

        found_pct = (confidences.get("HIGH", 0) + confidences.get("LOW", 0)) / max(total, 1)
        gate("≥87% teams discovered (Gate 1→2)", found_pct >= 0.87, f"{found_pct:.0%} found")

        # BUG 5 FIX: use cloned_count (sum of success+empty+sparse), not clone_statuses["complete"]
        gate("≥220 repos cloned (Gate 2→3)", cloned_count >= 220, f"{cloned_count} cloned")

        review_pass_rate = complete_count / max(total, 1)
        gate(
            "≥90% reviews valid (Gate 3→4)",
            review_pass_rate >= 0.90,
            f"{review_pass_rate:.0%} complete",
        )

        all_knowledge = all(knowledge_files.values())
        gate("All knowledge files present (Gate 4→done)", all_knowledge)

        print(color("\n" + sep, BOLD, use_color))

    # ── Failed / Pending teams ────────────────────────────────────────
    failed = [t for t in manifest if t.get("review_status") == "failed"]
    pending = [t for t in manifest if t.get("review_status") == "pending"]
    not_found = [t for t in manifest if t.get("confidence") == "NOT_FOUND"]

    if failed:
        print(color(f"\n  FAILED REVIEWS ({len(failed)}) — need attention:", RED + BOLD, use_color))
        for t in failed:
            print(color(f"    - {t['team_name']}", RED, use_color))

    if pending and (failed_only or verbose):
        print(color(f"\n  PENDING REVIEWS ({len(pending)}):", YELLOW + BOLD, use_color))
        for t in pending[:20]:
            print(color(f"    - {t['team_name']}", YELLOW, use_color))
        if len(pending) > 20:
            print(color(f"    ... and {len(pending) - 20} more", DIM, use_color))

    if not_found and verbose:
        print(color(f"\n  NOT FOUND ({len(not_found)}) — need manual recovery:", RED + BOLD, use_color))
        for t in not_found:
            print(color(f"    - {t['team_name']}", RED, use_color))

    if not failed and not failed_only:
        print(color("  No failed reviews. 🎉\n", GREEN, use_color))


def main():
    parser = argparse.ArgumentParser(description="DEVTrails Intel — Pipeline Progress Dashboard")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Also list LOW_CONFIDENCE, NOT_FOUND, and pending team names")
    parser.add_argument("--failed-only", action="store_true",
                        help="Print only failed/pending teams and exit")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colour output")
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()
    manifest = load_manifest()
    print_dashboard(manifest, verbose=args.verbose, failed_only=args.failed_only, use_color=use_color)


if __name__ == "__main__":
    main()
