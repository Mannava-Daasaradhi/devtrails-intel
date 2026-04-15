# =============================================================================
# src/01_search_repos.py — DEVTrails 2026 Competitive Intelligence Pipeline
# Phase 1: GitHub Repository Discovery
#
# Reads:   teams.txt  (via name_sanitizer)
#          team_name_map.json
# Writes:  repos_manifest.json
#          not_found.txt
#          low_confidence.txt
#          logs/01_search_repos_{timestamp}.log
#
# Run from project root:
#   python src/01_search_repos.py
#
# Resume-safe: if repos_manifest.json already exists, teams already recorded
# (any status) are skipped. Delete repos_manifest.json to start fresh.
# =============================================================================

import json
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Project root must be on sys.path so we can import config + utils.
# When running as `python src/01_search_repos.py` from the project root,
# cwd is the project root but 'src' is NOT on sys.path — add it explicitly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    TEAMS_FILE,
    NAME_MAP_FILE,
    MANIFEST_FILE,
    NOT_FOUND_FILE,
    LOW_CONFIDENCE_FILE,
    LOGS_DIR,
    HIGH_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    GITHUB_SEARCH_DELAY,
)
from utils.name_sanitizer import load_name_map
from utils.github_client import SESSION, find_best_repo, print_rate_limit_status


# =============================================================================
# Logging — writes to stdout AND a timestamped log file simultaneously
# =============================================================================

def setup_logging() -> logging.Logger:
    logs_dir = PROJECT_ROOT / LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"01_search_repos_{timestamp}.log"

    logger = logging.getLogger("search_repos")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    # File handler — full DEBUG level
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — INFO and above only
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Logging to {log_file}")
    return logger


# =============================================================================
# Manifest helpers
# =============================================================================

def load_manifest(manifest_path: Path) -> list[dict]:
    """Load existing manifest JSON, or return empty list if it doesn't exist."""
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(
                f"Manifest file '{manifest_path}' is corrupt or unreadable: {exc}\n"
                "Delete it and re-run to start fresh."
            )
    return []


def save_manifest(manifest: list[dict], manifest_path: Path) -> None:
    """Atomically write manifest to disk (write to .tmp then rename)."""
    tmp_path = manifest_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(manifest_path)


def already_searched(team_name: str, manifest: list[dict]) -> bool:
    """Return True if this team already has an entry in the manifest."""
    return any(entry["team_name"] == team_name for entry in manifest)


# =============================================================================
# Side-file writers
# =============================================================================

def write_not_found(team_names: list[str], path: Path) -> None:
    """Write or overwrite not_found.txt from the current NOT_FOUND list."""
    path.write_text("\n".join(team_names) + ("\n" if team_names else ""), encoding="utf-8")


def write_low_confidence(entries: list[dict], path: Path) -> None:
    """
    Write or overwrite low_confidence.txt.
    Each line: <score>  <confidence>  <url>  <team_name>
    Tab-separated so it's easy to open in a spreadsheet.
    """
    lines = []
    for e in entries:
        lines.append(
            f"{e['score']:>4}\t{e['confidence']:<4}\t"
            f"{e.get('repo_url') or 'N/A'}\t{e['team_name']}"
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# =============================================================================
# Core: process one team
# =============================================================================

def process_team(
    team_name: str,
    safe_name: str,
    session,
    logger: logging.Logger,
) -> dict:
    """
    Run the full discovery pipeline for one team via github_client.find_best_repo().
    Fills in safe_name and clone_path, which find_best_repo() leaves blank.

    Returns a manifest entry dict.
    """
    logger.info(f"Searching: {team_name!r}")

    result = find_best_repo(team_name, session=session)

    # Fill caller-owned fields
    result["safe_name"] = safe_name
    result["clone_path"] = str(Path("repos") / safe_name)

    confidence = result["confidence"]
    score = result["score"]
    repo_url = result.get("repo_url") or "—"
    fallback = result.get("search_fallback_level", -1)

    if confidence == "NOT_FOUND":
        logger.warning(f"  NOT_FOUND after all fallbacks: {team_name!r}")
    elif confidence == "HIGH":
        logger.info(f"  HIGH  score={score}  fallback={fallback}  {repo_url}")
    else:
        logger.info(f"  LOW   score={score}  fallback={fallback}  {repo_url}")

    return result


# =============================================================================
# Summary printer
# =============================================================================

def print_summary(manifest: list[dict], logger: logging.Logger, elapsed: float) -> None:
    total = len(manifest)
    high  = sum(1 for e in manifest if e["confidence"] == "HIGH")
    low   = sum(1 for e in manifest if e["confidence"] == "LOW")
    nf    = sum(1 for e in manifest if e["confidence"] == "NOT_FOUND")

    fallback_dist: dict[int, int] = {}
    for e in manifest:
        lvl = e.get("search_fallback_level", -1)
        fallback_dist[lvl] = fallback_dist.get(lvl, 0) + 1

    logger.info("=" * 60)
    logger.info(f"PHASE 1 COMPLETE — {total} teams processed in {elapsed:.0f}s")
    logger.info(f"  HIGH confidence : {high}")
    logger.info(f"  LOW  confidence : {low}")
    logger.info(f"  NOT_FOUND       : {nf}")
    logger.info(f"  Discovery rate  : {(high + low) / total * 100:.1f}%  (target >87%)")
    logger.info("Fallback level distribution:")
    for lvl in sorted(fallback_dist):
        label = {
            0: "primary query",
            1: "fallback 1 (no year)",
            2: "fallback 2 (guidewire hackathon)",
            3: "fallback 3 (no quotes)",
            4: "code search",
           -1: "not found",
        }.get(lvl, f"level {lvl}")
        logger.info(f"  [{lvl:>2}] {label}: {fallback_dist[lvl]}")

    # Quality gate hints
    if nf > 35:
        logger.warning(
            f"QUALITY GATE WARNING: {nf} NOT_FOUND teams exceeds threshold of 35. "
            "Check that your primary query template matches the hackathon tag used in repos."
        )
    fb_2plus = sum(v for k, v in fallback_dist.items() if k >= 2)
    if fb_2plus > 50:
        logger.warning(
            f"QUALITY GATE WARNING: {fb_2plus} teams needed fallback level 2+. "
            "Your primary query may be wrong — check GITHUB_SEARCH_QUERY_TEMPLATE in config.py."
        )


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    logger = setup_logging()
    start_time = time.monotonic()

    # ---- Load name map -------------------------------------------------------
    try:
        NAME_MAP, _SAFE_MAP = load_name_map(str(PROJECT_ROOT / NAME_MAP_FILE))
    except FileNotFoundError:
        logger.error(
            f"team_name_map.json not found at '{NAME_MAP_FILE}'.\n"
            "Run: python utils/name_sanitizer.py   first."
        )
        sys.exit(1)

    all_teams = list(NAME_MAP.keys())
    logger.info(f"Loaded {len(all_teams)} teams from {NAME_MAP_FILE}")

    # ---- Load or initialise manifest -----------------------------------------
    manifest_path = PROJECT_ROOT / MANIFEST_FILE
    manifest = load_manifest(manifest_path)

    already_done = {e["team_name"] for e in manifest}
    remaining = [t for t in all_teams if t not in already_done]

    if already_done:
        logger.info(
            f"Resuming: {len(already_done)} teams already in manifest, "
            f"{len(remaining)} remaining."
        )
    else:
        logger.info(f"Fresh run: {len(remaining)} teams to search.")

    if not remaining:
        logger.info("Nothing to do — all teams already in manifest.")
    else:
        # ---- Confirm token + show rate limit headroom ----------------------------
        logger.info("Checking GitHub rate limits...")
        print_rate_limit_status(SESSION)

        # ---- Process teams -------------------------------------------------------
        not_found: list[str] = [e["team_name"] for e in manifest if e["confidence"] == "NOT_FOUND"]
        low_conf: list[dict] = [e for e in manifest if e["confidence"] == "LOW"]

        for i, team_name in enumerate(remaining, start=1):
            safe_name = NAME_MAP[team_name]

            logger.info(f"[{i}/{len(remaining)}] Processing: {team_name!r}")

            try:
                entry = process_team(team_name, safe_name, SESSION, logger)
            except KeyboardInterrupt:
                logger.warning("Interrupted by user. Saving manifest and exiting.")
                save_manifest(manifest, manifest_path)
                sys.exit(0)
            except Exception as exc:
                # Don't let one bad team kill the whole run.
                logger.error(f"Unexpected error for {team_name!r}: {exc}", exc_info=True)
                entry = {
                    "team_name": team_name,
                    "safe_name": safe_name,
                    "repo_url": None,
                    "confidence": "NOT_FOUND",
                    "score": 0,
                    "clone_path": str(Path("repos") / safe_name),
                    "clone_status": "pending",
                    "review_status": "pending",
                    "search_fallback_level": -1,
                    "owner": None,
                    "repo_name": None,
                    "repo_size_kb": 0,
                    "error": str(exc),
                }

            manifest.append(entry)

            # Track side-file lists in memory
            if entry["confidence"] == "NOT_FOUND":
                not_found.append(team_name)
            elif entry["confidence"] == "LOW":
                low_conf.append(entry)

            # Save manifest after every team — crash-safe.
            save_manifest(manifest, manifest_path)

            # Small delay between teams (GITHUB_SEARCH_DELAY already applied inside
            # github_client for each individual query; this is an extra inter-team gap).
            if i < len(remaining):
                time.sleep(0.5)

        # ---- Write side files ------------------------------------------------
        not_found_path = PROJECT_ROOT / NOT_FOUND_FILE
        write_not_found(not_found, not_found_path)
        logger.info(f"not_found.txt written: {len(not_found)} teams")

        low_conf_path = PROJECT_ROOT / LOW_CONFIDENCE_FILE
        write_low_confidence(low_conf, low_conf_path)
        logger.info(f"low_confidence.txt written: {len(low_conf)} teams")

    # ---- Summary -------------------------------------------------------------
    elapsed = time.monotonic() - start_time
    print_summary(manifest, logger, elapsed)

    logger.info(f"Manifest saved to '{MANIFEST_FILE}' ({len(manifest)} entries)")
    logger.info("Next step: python src/02_clone_repos.py")


if __name__ == "__main__":
    main()