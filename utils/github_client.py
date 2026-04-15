# =============================================================================
# utils/github_client.py — DEVTrails 2026 Competitive Intelligence Pipeline
# All GitHub API interactions live here. No other script talks to GitHub directly.
#
# Covers:
#   - Authenticated session setup
#   - Repository search with exponential backoff (4-query fallback sequence)
#   - Code search fallback (last resort, separate rate limit)
#   - README pre-fetch and keyword scoring
#   - Repo scoring logic
#   - Rate limit awareness utilities
# =============================================================================

import time
import base64
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from config import (
    GITHUB_TOKEN,
    GITHUB_SEARCH_DELAY,
    GITHUB_SEARCH_QUERY_TEMPLATE,
    README_PREFETCH_TOP_N,
    HIGH_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
)

# =============================================================================
# Session — built once, reused everywhere
# =============================================================================

def build_session() -> requests.Session:
    """
    Return a requests.Session pre-configured with GitHub auth headers.
    Using a session reuses the underlying TCP connection across calls — important
    when making 265+ sequential requests.
    """
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "devtrails-intel/1.3",
    })
    return session


# Module-level session — import and use directly in other scripts.
# Call build_session() explicitly if you need a fresh session (e.g. in tests).
SESSION = build_session()


# =============================================================================
# Core: search with exponential backoff
# =============================================================================

def _search_repos(query: str, session: requests.Session, max_retries: int = 5) -> Optional[dict]:
    """
    Execute one GitHub repository search query with exponential backoff on 429/403.

    Returns the parsed JSON response dict on success, or None if all retries fail.
    Does NOT apply the inter-request sleep — callers are responsible for that.
    """
    for attempt in range(max_retries):
        try:
            resp = session.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "updated", "order": "desc", "per_page": 10},
                timeout=30,
            )
        except requests.RequestException as exc:
            print(f"  Network error on attempt {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(5)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code in (403, 429):
            # Check for Retry-After header first (GitHub sometimes sends it).
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                wait = int(retry_after) + 1
            else:
                wait = (2 ** attempt) * 5   # 5s, 10s, 20s, 40s, 80s
            print(f"  Rate limited (HTTP {resp.status_code}). Waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue

        # Any other HTTP error is unexpected — surface it immediately.
        print(
            f"  Unexpected HTTP {resp.status_code} for query: {query!r}\n"
            f"  Response: {resp.text[:200]}",
            file=sys.stderr,
        )
        resp.raise_for_status()

    print(f"  Exhausted {max_retries} retries for query: {query!r}", file=sys.stderr)
    return None


# =============================================================================
# Multi-query fallback sequence
# =============================================================================

def search_with_fallbacks(
    team_name: str,
    session: Optional[requests.Session] = None,
) -> tuple[Optional[dict], int]:
    """
    Try up to 4 progressively looser repository search queries for a team.
    Stops at the first query that returns results.

    Returns (result_dict, fallback_level) where:
      fallback_level 0 = primary query matched
      fallback_level 1-3 = fallback queries
      fallback_level -1 = no results from any repo search query

    The caller should then try code_search_fallback() if this returns (-1).
    """
    if session is None:
        session = SESSION

    # Strip quotes from the team name so they don't break URL encoding.
    safe_query_name = team_name.replace('"', "").strip()

    queries = [
        f'"{safe_query_name}" DEVTrails 2026',         # primary: exact name + event + year
        f'"{safe_query_name}" DEVTrails',               # drop year (some teams skip it)
        f'"{safe_query_name}" guidewire hackathon',     # drop event name entirely
        f'{safe_query_name} DEVTrails 2026',            # no quotes (for multi-word names)
    ]

    for i, query in enumerate(queries):
        result = _search_repos(query, session)
        if result and result.get("total_count", 0) > 0:
            if i > 0:
                print(f"  [{team_name}] Found on fallback query {i + 1}: {query!r}")
            return result, i
        time.sleep(GITHUB_SEARCH_DELAY)

    return None, -1


def code_search_fallback(
    team_name: str,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Last-resort search inside file contents using the GitHub Code Search API.
    Finds repos where the team name only appears in source code/docs, not the
    repo name or description.

    Returns a list of repository dicts (same shape as items[*].repository in
    a regular search result), deduplicated by full_name.

    NOTE: Code search has a SEPARATE rate limit (10 req/min authenticated).
    Only call this for teams that exhausted all repo search fallbacks.
    """
    if session is None:
        session = SESSION

    safe_query_name = team_name.replace('"', "").strip()
    query = f'"{safe_query_name}" "DEVTrails" language:markdown'

    try:
        resp = session.get(
            "https://api.github.com/search/code",
            params={"q": query, "per_page": 5},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"  Code search network error for {team_name!r}: {exc}", file=sys.stderr)
        return []

    if resp.status_code in (403, 429):
        wait = int(resp.headers.get("Retry-After", 60)) + 1
        print(f"  Code search rate limited. Waiting {wait}s...", file=sys.stderr)
        time.sleep(wait)
        return []

    if resp.status_code != 200:
        print(f"  Code search HTTP {resp.status_code} for {team_name!r}", file=sys.stderr)
        return []

    items = resp.json().get("items", [])
    if not items:
        return []

    # Deduplicate by full_name — multiple matching files may be in the same repo.
    seen: dict[str, dict] = {}
    for item in items:
        repo = item.get("repository", {})
        full_name = repo.get("full_name")
        if full_name and full_name not in seen:
            seen[full_name] = repo

    return list(seen.values())


# =============================================================================
# README pre-fetch
# =============================================================================

_README_KEYWORDS = {"guidewire", "devtrails", "hackathon", "insurancesuite"}


def fetch_readme(owner: str, repo: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """
    Fetch and decode the README for a given repo.
    Returns the decoded text, or None if the README doesn't exist or can't be fetched.
    Does NOT apply any sleep — caller is responsible.
    """
    if session is None:
        session = SESSION

    try:
        resp = session.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            timeout=20,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    data = resp.json()
    encoded = data.get("content", "")
    try:
        return base64.b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
        return None


def readme_has_keywords(text: str) -> bool:
    """Return True if the README text contains any of the target keywords."""
    lowered = text.lower()
    return any(kw in lowered for kw in _README_KEYWORDS)


# =============================================================================
# Repo scoring
# =============================================================================

_SIX_MONTHS_AGO = datetime.now(timezone.utc) - timedelta(days=183)


def score_repo(repo: dict, team_name: str, readme_text: Optional[str] = None) -> int:
    """
    Score a single GitHub repo dict against the team name and optional README text.

    Scoring table (from blueprint Section 4.2):
      +4  repo name or description contains "devtrails" (case-insensitive)
      +2  repo name or description contains "2026"
      +3  README contains a target keyword (guidewire / devtrails / hackathon)
      +2  repo pushed within the last 6 months
      +2  repo description contains team name (partial match)
      -5  repo is a fork
      -3  repo has 0 commits (open_issues_count proxy is unreliable; use size == 0)
      -4  repo is archived

    Returns the integer score (can be negative).
    """
    score = 0
    name = (repo.get("name") or "").lower()
    description = (repo.get("description") or "").lower()
    team_lower = team_name.lower()

    # Positive signals
    if "devtrails" in name or "devtrails" in description:
        score += 4
    if "2026" in name or "2026" in description:
        score += 2
    if readme_text and readme_has_keywords(readme_text):
        score += 3
    if team_lower in description:
        score += 2

    # Recency: pushed_at within last 6 months
    pushed_at_str = repo.get("pushed_at") or ""
    if pushed_at_str:
        try:
            pushed_at = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
            if pushed_at >= _SIX_MONTHS_AGO:
                score += 2
        except ValueError:
            pass

    # Negative signals
    if repo.get("fork"):
        score -= 5
    if repo.get("size", 1) == 0:
        score -= 3   # empty repo — size field is in KB; 0 means nothing pushed
    if repo.get("archived"):
        score -= 4

    return score


def confidence_label(score: int) -> str:
    """Map a numeric score to a confidence label string."""
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "HIGH"
    if score >= LOW_CONFIDENCE_THRESHOLD:
        return "LOW"
    return "LOW"   # even sub-threshold results get LOW, not NOT_FOUND — see blueprint 4.2


# =============================================================================
# Top-level: find best repo for a team
# =============================================================================

def find_best_repo(
    team_name: str,
    session: Optional[requests.Session] = None,
) -> dict:
    """
    Full discovery pipeline for a single team:
      1. Run 4-query repo search fallback sequence.
      2. For top README_PREFETCH_TOP_N candidates, fetch README and re-score.
      3. If still no results, try code search.
      4. Return a result dict ready to be written into repos_manifest.json.

    Result dict fields:
      team_name, safe_name (caller fills this), repo_url, confidence, score,
      clone_path (caller fills this), clone_status, review_status,
      search_fallback_level, owner, repo_name, repo_size_kb
    """
    if session is None:
        session = SESSION

    result_base = {
        "team_name": team_name,
        "safe_name": "",          # filled by caller via NAME_MAP
        "repo_url": None,
        "confidence": "NOT_FOUND",
        "score": 0,
        "clone_path": "",         # filled by caller
        "clone_status": "pending",
        "review_status": "pending",
        "search_fallback_level": -1,
        "owner": None,
        "repo_name": None,
        "repo_size_kb": 0,
    }

    # --- Step 1: repo search with fallbacks ---
    search_result, fallback_level = search_with_fallbacks(team_name, session)
    result_base["search_fallback_level"] = fallback_level

    candidates: list[dict] = []

    if search_result and search_result.get("total_count", 0) > 0:
        candidates = search_result.get("items", [])

    else:
        # --- Step 2: code search last resort ---
        print(f"  [{team_name}] All repo searches failed. Trying code search...")
        code_repos = code_search_fallback(team_name, session)
        time.sleep(GITHUB_SEARCH_DELAY)  # respect code search rate limit too

        if not code_repos:
            print(f"  [{team_name}] NOT_FOUND after all fallbacks.")
            return result_base

        # code_search_fallback returns raw repo dicts, not full search item dicts.
        # Wrap them minimally so score_repo can handle them.
        candidates = code_repos
        result_base["search_fallback_level"] = 4   # code search level

    # --- Step 3: score all candidates, fetch READMEs for top N ---
    # Initial score without README (fast pass to rank candidates).
    scored = [(score_repo(repo, team_name), repo) for repo in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Fetch README for top README_PREFETCH_TOP_N and re-score.
    for idx in range(min(README_PREFETCH_TOP_N, len(scored))):
        initial_score, repo = scored[idx]
        owner = (repo.get("owner") or {}).get("login") or repo.get("full_name", "").split("/")[0]
        repo_name = repo.get("name") or repo.get("full_name", "").split("/")[-1]
        if not owner or not repo_name:
            continue
        readme = fetch_readme(owner, repo_name, session)
        time.sleep(1)   # small gap — readme fetches don't count as search but still hit API
        if readme:
            scored[idx] = (score_repo(repo, team_name, readme_text=readme), repo)

    # Re-sort after README scoring.
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_repo = scored[0]

    # --- Step 4: build result ---
    owner = (best_repo.get("owner") or {}).get("login") or best_repo.get("full_name", "").split("/")[0]
    repo_name = best_repo.get("name") or best_repo.get("full_name", "").split("/")[-1]
    html_url = best_repo.get("html_url") or f"https://github.com/{owner}/{repo_name}"

    result_base.update({
        "repo_url": html_url,
        "confidence": confidence_label(best_score),
        "score": best_score,
        "owner": owner,
        "repo_name": repo_name,
        "repo_size_kb": best_repo.get("size", 0),
    })

    # Anything with results but score < LOW_CONFIDENCE_THRESHOLD still gets LOW,
    # not NOT_FOUND — blueprint Section 4.2: "never skip unless zero results".
    if best_score < LOW_CONFIDENCE_THRESHOLD:
        result_base["confidence"] = "LOW"

    return result_base


# =============================================================================
# Rate limit inspector (utility — call before a long run to check headroom)
# =============================================================================

def print_rate_limit_status(session: Optional[requests.Session] = None) -> None:
    """
    Print current GitHub API rate limit status to stdout.
    Useful to call at the start of a run to confirm token is working.
    """
    if session is None:
        session = SESSION

    try:
        resp = session.get("https://api.github.com/rate_limit", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"Could not fetch rate limit: {exc}", file=sys.stderr)
        return

    for resource_name in ("search", "core", "code_search"):
        resource = data.get("resources", {}).get(resource_name, {})
        remaining = resource.get("remaining", "?")
        limit = resource.get("limit", "?")
        reset_ts = resource.get("reset")
        reset_str = (
            datetime.fromtimestamp(reset_ts).strftime("%H:%M:%S")
            if reset_ts else "?"
        )
        print(f"  {resource_name:12s}: {remaining}/{limit} remaining, resets at {reset_str}")