# =============================================================================
# src/02_clone_repos.py — DEVTrails 2026 Competitive Intelligence Pipeline
# Phase 2: Repository Cloning
#
# Reads:   repos_manifest.json  (written by 01_search_repos.py)
# Writes:  repos/{safe_name}/   (one folder per team)
#          repos_manifest.json  (updated clone_status, file_count, repo_size_kb)
#          logs/02_clone_repos_{timestamp}.log
#
# Run from project root:
#   python src/02_clone_repos.py
#
# Resume-safe: teams where clone_status == "success" or "empty" are skipped.
# Parallelism: CLONE_PARALLEL_WORKERS (default 10) — git clone is I/O bound,
#   safe to parallelise. DO NOT increase REVIEW_PARALLEL_WORKERS — see config.py.
# =============================================================================

import json
import shutil
import subprocess
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    MANIFEST_FILE,
    REPOS_DIR,
    LOGS_DIR,
    INCLUDE_EXTENSIONS,
    MAX_REPO_SIZE_KB,
    CLONE_PARALLEL_WORKERS,
    DELETE_REPOS_AFTER_REVIEW,
)


# =============================================================================
# Logging
# =============================================================================

def setup_logging() -> logging.Logger:
    logs_dir = PROJECT_ROOT / LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"02_clone_repos_{timestamp}.log"

    logger = logging.getLogger("clone_repos")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Logging to {log_file}")
    return logger


# =============================================================================
# Manifest helpers (same atomic-write pattern as 01_search_repos.py)
# =============================================================================

def load_manifest(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"repos_manifest.json not found at '{manifest_path}'.\n"
            "Run: python src/01_search_repos.py  first."
        )
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Manifest corrupt or unreadable: {exc}")


def save_manifest(manifest: list[dict], manifest_path: Path) -> None:
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(manifest_path)


# =============================================================================
# File counting
# =============================================================================

# Use INCLUDE_EXTENSIONS from config rather than a hard-coded subset,
# so file_count reflects exactly what Phase 3 will actually review.
_CODE_EXTENSIONS = INCLUDE_EXTENSIONS - {".md", ".txt", ".rst"}  # docs excluded from count


def count_code_files(clone_path: Path) -> int:
    """Return the number of reviewable code files in the cloned repo."""
    return sum(
        1 for f in clone_path.rglob("*")
        if f.is_file() and f.suffix.lower() in _CODE_EXTENSIONS
    )


def disk_size_kb(clone_path: Path) -> int:
    """Return actual disk usage of the cloned directory in KB."""
    total_bytes = sum(
        f.stat().st_size for f in clone_path.rglob("*") if f.is_file()
    )
    return total_bytes // 1024


# =============================================================================
# Git operations
# =============================================================================

def _run_git(args: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """
    Run a git command. Raises subprocess.CalledProcessError on non-zero exit.
    stdout/stderr captured and returned in the result object.
    """
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def clone_shallow(repo_url: str, dest: Path, timeout: int = 300) -> None:
    """Standard shallow clone — depth 1, single branch."""
    _run_git(
        ["clone", "--depth", "1", "--single-branch", repo_url, str(dest)],
        timeout=timeout,
    )


def clone_sparse(repo_url: str, dest: Path, timeout: int = 300) -> None:
    """
    Sparse checkout for repos > MAX_REPO_SIZE_KB.
    Fetches only the folders most likely to contain application code.
    """
    dest.mkdir(parents=True, exist_ok=True)

    # Init the repo in the dest directory first
    _run_git(
        ["clone", "--depth", "1", "--filter=blob:none", "--sparse", repo_url, str(dest)],
        timeout=timeout,
    )

    # Then narrow to code-heavy folders
    sparse_dirs = ["src", "lib", "core", "app", "backend", "api", "frontend",
                   "server", "client", "main", "pkg"]
    _run_git(
        ["sparse-checkout", "set"] + sparse_dirs,
        cwd=dest,
        timeout=60,
    )


# =============================================================================
# Single-team clone logic
# =============================================================================

def clone_team(entry: dict, repos_dir: Path, logger: logging.Logger) -> dict:
    """
    Clone one team's repository. Returns an updated copy of the manifest entry.

    clone_status values:
      success  — cloned, has code files
      empty    — cloned, but zero reviewable code files found
      sparse   — cloned with sparse checkout (large repo)
      skipped  — repo_url is None (NOT_FOUND from Phase 1)
      failed   — git clone raised an error
    """
    team_name = entry["team_name"]
    safe_name = entry["safe_name"]
    repo_url = entry.get("repo_url")
    repo_size_kb = entry.get("repo_size_kb", 0)

    updated = dict(entry)  # work on a copy

    # ---- Skip NOT_FOUND teams ------------------------------------------------
    if not repo_url:
        logger.info(f"  SKIPPED (no repo URL): {team_name!r}")
        updated["clone_status"] = "skipped"
        return updated

    dest = repos_dir / safe_name

    # ---- Resumability: skip if .git already exists ---------------------------
    if (dest / ".git").exists():
        file_count = count_code_files(dest)
        logger.info(f"  ALREADY CLONED — {file_count} code files: {team_name!r}")
        updated["clone_status"] = updated.get("clone_status", "success")
        updated["file_count"] = file_count
        return updated

    # ---- Perform clone -------------------------------------------------------
    dest.mkdir(parents=True, exist_ok=True)
    use_sparse = repo_size_kb > MAX_REPO_SIZE_KB

    try:
        if use_sparse:
            logger.info(f"  SPARSE clone ({repo_size_kb:,} KB > {MAX_REPO_SIZE_KB:,} KB limit): {team_name!r}")
            clone_sparse(repo_url, dest)
            clone_status = "sparse"
        else:
            logger.info(f"  Cloning ({repo_size_kb:,} KB): {team_name!r}")
            clone_shallow(repo_url, dest)
            clone_status = "success"

    except subprocess.TimeoutExpired:
        logger.warning(f"  TIMEOUT cloning {team_name!r} — removing partial clone")
        shutil.rmtree(dest, ignore_errors=True)
        updated["clone_status"] = "failed"
        updated["clone_error"] = "timeout"
        return updated

    except subprocess.CalledProcessError as exc:
        logger.warning(
            f"  FAILED cloning {team_name!r}: {exc.stderr.strip()[:200]}"
        )
        shutil.rmtree(dest, ignore_errors=True)
        updated["clone_status"] = "failed"
        updated["clone_error"] = exc.stderr.strip()[:200]
        return updated

    # ---- Post-clone checks ---------------------------------------------------
    file_count = count_code_files(dest)
    actual_size_kb = disk_size_kb(dest)

    if file_count == 0:
        logger.warning(f"  EMPTY repo (no code files): {team_name!r}")
        clone_status = "empty"

    logger.info(
        f"  {'SPARSE ' if use_sparse else ''}"
        f"{'EMPTY ' if file_count == 0 else ''}"
        f"OK — {file_count} code files, {actual_size_kb:,} KB on disk: {team_name!r}"
    )

    updated["clone_status"] = clone_status
    updated["file_count"] = file_count
    updated["repo_size_kb"] = actual_size_kb  # overwrite with actual disk size

    return updated


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    logger = setup_logging()
    start_time = time.monotonic()

    manifest_path = PROJECT_ROOT / MANIFEST_FILE
    repos_dir = PROJECT_ROOT / REPOS_DIR
    repos_dir.mkdir(parents=True, exist_ok=True)

    # ---- Load manifest -------------------------------------------------------
    try:
        manifest = load_manifest(manifest_path)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error(str(exc))
        sys.exit(1)

    # ---- Determine what needs cloning ----------------------------------------
    # Skip: already succeeded, already empty (no code), or skipped (no URL).
    done_statuses = {"success", "empty", "sparse", "skipped"}
    to_clone = [e for e in manifest if e.get("clone_status") not in done_statuses]
    already_done = len(manifest) - len(to_clone)

    logger.info(
        f"Manifest: {len(manifest)} teams total. "
        f"{already_done} already cloned, {len(to_clone)} remaining."
    )

    if not to_clone:
        logger.info("Nothing to clone — all teams already processed.")
    else:
        logger.info(f"Cloning with {CLONE_PARALLEL_WORKERS} parallel workers...")

        # Build a lookup for fast manifest update by team_name
        manifest_index: dict[str, int] = {e["team_name"]: i for i, e in enumerate(manifest)}

        completed_count = 0
        failed_count = 0

        # ThreadPoolExecutor is safe here because git clone is network/I/O bound.
        # Each thread runs a subprocess — no GIL contention, no shared state.
        with ThreadPoolExecutor(max_workers=CLONE_PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(clone_team, entry, repos_dir, logger): entry["team_name"]
                for entry in to_clone
            }

            for future in as_completed(futures):
                team_name = futures[future]
                try:
                    updated_entry = future.result()
                except Exception as exc:
                    # Should not reach here — clone_team catches its own errors,
                    # but guard against unexpected exceptions anyway.
                    logger.error(f"Unhandled error for {team_name!r}: {exc}", exc_info=True)
                    updated_entry = {
                        **manifest[manifest_index[team_name]],
                        "clone_status": "failed",
                        "clone_error": str(exc),
                    }

                # Update manifest in-place
                idx = manifest_index[team_name]
                manifest[idx] = updated_entry

                status = updated_entry.get("clone_status", "unknown")
                if status == "failed":
                    failed_count += 1
                else:
                    completed_count += 1

                # Save after every completion — crash-safe
                save_manifest(manifest, manifest_path)

    # ---- Summary -------------------------------------------------------------
    elapsed = time.monotonic() - start_time

    status_counts: dict[str, int] = {}
    for e in manifest:
        s = e.get("clone_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    total_code_files = sum(e.get("file_count", 0) for e in manifest)
    total_disk_kb = sum(e.get("repo_size_kb", 0) for e in manifest)

    logger.info("=" * 60)
    logger.info(f"PHASE 2 COMPLETE — {len(manifest)} teams in {elapsed:.0f}s")
    for status, count in sorted(status_counts.items()):
        logger.info(f"  {status:<10}: {count}")
    logger.info(f"  Total code files : {total_code_files:,}")
    logger.info(f"  Total disk usage : {total_disk_kb / 1024:.1f} MB")

    # Quality gate hints
    failed = status_counts.get("failed", 0)
    empty  = status_counts.get("empty", 0)
    if failed > 10:
        logger.warning(f"QUALITY GATE WARNING: {failed} clone failures. Check network or token.")
    if empty > 20:
        logger.warning(
            f"QUALITY GATE WARNING: {empty} empty repos (no code files). "
            "These will produce weak reviews — check them manually."
        )

    logger.info(f"Manifest saved to '{MANIFEST_FILE}'")
    logger.info("Next step: python src/03_review_repos.py")


if __name__ == "__main__":
    main()
