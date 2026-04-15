# DEVTrails 2026 — Competitive Intelligence System
## Master Blueprint v1.3

> **How to use this document:** This is a living blueprint. Each reviewer reads it fully, identifies weaknesses, adds improvements inline under the relevant section using `> [REVIEWER N NOTE]` blocks, then updates the version number. Do not delete previous reviewer notes — they are part of the audit trail.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Project Folder Structure](#2-project-folder-structure)
3. [Phase 0 — Team Name Collection](#3-phase-0--team-name-collection)
4. [Phase 1 — GitHub Repository Discovery](#4-phase-1--github-repository-discovery)
5. [Phase 2 — Repository Cloning](#5-phase-2--repository-cloning)
6. [Phase 3 — Deep Code Review Engine](#6-phase-3--deep-code-review-engine)
7. [Phase 4 — Knowledge Synthesis](#7-phase-4--knowledge-synthesis)
8. [Prompt Architecture (Critical)](#8-prompt-architecture-critical)
9. [Ollama Model Selection](#9-ollama-model-selection)
10. [Failure Modes and Mitigations](#10-failure-modes-and-mitigations)
11. [Execution Order and Run Strategy](#11-execution-order-and-run-strategy)
12. [config.py Reference](#12-configpy-reference)
13. [Quality Gates](#13-quality-gates)

---

## 1. System Overview

**Goal:** Analyse the GitHub repositories of all 265 competing DEVTrails 2026 teams with enough depth that you can reconstruct their implementation from your notes alone — then use that knowledge to identify gaps, rare innovations, and features worth building into your own submission.

**Constraint:** Everything runs locally. No cloud APIs except GitHub's search API (rate-limited but free with a token). All LLM inference goes through Ollama. No shortcuts — weak output at any phase ruins every downstream phase.

**Philosophy:** The pipeline is only as strong as Phase 3 (the `.md` files). Every design decision in Phase 1 and 2 exists solely to maximise the quality of those 265 files. Phase 4 is worthless if Phase 3 is weak.

**Output files:**

| File | Description |
|------|-------------|
| `teams.txt` | 265 team names, one per line |
| `team_name_map.json` | Maps safe filenames → original team names |
| `not_found.txt` | Teams where no repo was found |
| `low_confidence.txt` | Teams where repo was found but with low confidence |
| `repos/{team_name}/` | Shallow-cloned repos |
| `reviews/{team_name}.md` | Deep code review — one per team |
| `knowledge/MASTER_PATTERNS.md` | Aggregated tech stack and feature frequencies |
| `knowledge/GAPS.md` | Features rare across the competition |
| `knowledge/YOUR_FEATURE_PLAN.md` | Personalised feature plan for your repo |

---

## 2. Project Folder Structure

```
devtrails-intel/
├── teams.txt
├── not_found.txt            ← auto-generated
├── low_confidence.txt       ← auto-generated (team name + URL + confidence score)
├── repos/
│   └── {team_name}/         ← one folder per team
├── reviews/
│   └── {team_name}.md       ← one review per team
├── knowledge/
│   ├── MASTER_PATTERNS.md
│   ├── GAPS.md
│   └── YOUR_FEATURE_PLAN.md
├── src/
│   ├── 00_collect_teams.py      ← optional scraping helper
│   ├── 01_search_repos.py       ← GitHub search + repo URL resolution
│   ├── 02_clone_repos.py        ← git clone --depth 1
│   ├── 03_review_repos.py       ← file walking + chunking + Ollama review
│   ├── 04_synthesize.py         ← pattern extraction + gap mapping
│   ├── 05_dashboard.py          ← ← NEW: progress status viewer (see Section 11.5)
│   └── utils/
│       ├── file_walker.py
│       ├── chunker.py
│       ├── ollama_client.py
│       ├── validator.py
│       ├── github_client.py
│       └── name_sanitizer.py
├── config.py
├── run_all.py
└── logs/
    └── run_{timestamp}.log
```

---

## 3. Phase 0 — Team Name Collection

### Goal
Produce `teams.txt` — 265 team names, one per line, exactly as they appear on the leaderboard.

### Method
This is a manual step but can be semi-automated. Two approaches:

**Option A — Manual copy-paste:**
Open the DEVTrails leaderboard. Select all team names. Paste into a text editor. Clean up formatting. Save as UTF-8. This takes ~10 minutes for 265 names.

**Option B — DOM scraping (if leaderboard is a webpage):**
Write a browser console snippet to extract team name elements:
```javascript
// Run in browser DevTools console on the leaderboard page
// Adjust the selector to match the actual DOM structure
const names = [...document.querySelectorAll('.team-name-selector')]
  .map(el => el.innerText.trim());
console.log(names.join('\n'));
```
Copy the output into `teams.txt`.

**Option C — `00_collect_teams.py` (if leaderboard has a stable URL and no auth wall):**
This is the `src/00_collect_teams.py` helper referenced in the folder structure. It automates Option B using `requests` + `BeautifulSoup`. Only use this if you have confirmed the leaderboard URL is publicly accessible without login.
```python
# src/00_collect_teams.py — minimal scraping helper
import requests
from bs4 import BeautifulSoup
from pathlib import Path

LEADERBOARD_URL = "https://your-leaderboard-url-here"  # set this in config.py

def scrape_team_names():
    resp = requests.get(LEADERBOARD_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    # Adjust selector to match the actual leaderboard DOM
    elements = soup.select('.team-name-selector')
    names = [el.get_text(strip=True) for el in elements]
    Path('teams.txt').write_text('\n'.join(names), encoding='utf-8')
    print(f"Wrote {len(names)} team names to teams.txt")

if __name__ == '__main__':
    scrape_team_names()
```
If the leaderboard requires a login or is a JavaScript SPA, fall back to Option A (manual) or Option B (browser console). Do not waste time automating a scrape that requires auth.

### Formatting Rules for teams.txt
- **One team name per line**
- **Exact casing** — "Team Alpha" and "team alpha" are different search strings
- **No trailing spaces** — the script strips per-line whitespace but casing is kept
- **No blank lines** — blank lines will be treated as a team name and waste an API call
- **UTF-8 encoding** — some names may contain accented characters or Japanese/Korean text
- **No quotes** — do not wrap names in quotes

### Verification Step
After creating `teams.txt`, run:
```bash
python -c "
lines = open('teams.txt').read().splitlines()
print(f'Total teams: {len(lines)}')
print(f'Unique teams: {len(set(lines))}')
dupes = [l for l in lines if lines.count(l) > 1]
if dupes: print(f'DUPLICATES: {set(dupes)}')
else: print('No duplicates found')
"
```
Expected: 265 total, 265 unique. Fix any duplicates before proceeding.

### Name Sanitization (Run Immediately After Verification)

Team names may contain characters that break file paths on all operating systems (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`). Run `name_sanitizer.py` immediately after verifying `teams.txt`. It produces `team_name_map.json` which every downstream script reads instead of using raw team names for paths.

```python
# utils/name_sanitizer.py
import re, json
from pathlib import Path
from collections import defaultdict

def sanitize_name(name: str) -> str:
    """Convert a team name to a safe filesystem name. Deterministic and reversible via map."""
    safe = re.sub(r'[\\/*?:"<>|]', '_', name)  # replace illegal chars
    safe = re.sub(r'\s+', ' ', safe).strip()     # normalise whitespace
    safe = safe[:100]                             # cap length
    return safe

def build_name_map(teams_file='teams.txt', output='team_name_map.json'):
    names = Path(teams_file).read_text(encoding='utf-8').splitlines()
    mapping = {}
    # BUG FIX (v1.3): Previous version had a collision counter bug.
    # If teams A, B, C all sanitize to "X", B got "X_1" and C also got "X_1"
    # because the count of "X" was still 1 when processing C (B's entry is "X_1", not "X").
    # Fix: use a dedicated collision counter dict, not list.count().
    collision_counter = defaultdict(int)
    for name in names:
        safe = sanitize_name(name)
        if safe in mapping.values():
            collision_counter[safe] += 1
            safe = f"{safe}_{collision_counter[safe]}"
        mapping[name] = safe  # original → safe
    Path(output).write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    print(f"Name map written: {len(mapping)} entries")
    return mapping
```

**Usage in every downstream script:**
```python
import json
NAME_MAP = json.loads(open('team_name_map.json').read())  # original → safe
SAFE_NAME = {v: k for k, v in NAME_MAP.items()}           # safe → original

# Always use NAME_MAP[team_name] for any path construction:
clone_path = Path(f"repos/{NAME_MAP[team_name]}/")
review_path = Path(f"reviews/{NAME_MAP[team_name]}.md")
```

---

## 4. Phase 1 — GitHub Repository Discovery

**Script:** `src/01_search_repos.py`

### 4.1 GitHub Search API

Use the GitHub Search API — not scraping. Endpoint:
```
GET https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=10
```

Query format: `"{team_name}" DEVTrails 2026`

**Authentication (mandatory):**
Create a GitHub Personal Access Token at `github.com/settings/tokens`. Scopes needed: none (public repo search is unauthenticated-compatible, but the token raises your limit from 10 req/min to 30 req/min for search). Add to `config.py` as `GITHUB_TOKEN`.

Rate limits:
- Unauthenticated: 10 search requests/minute → will take 26+ minutes and likely hit limits
- Authenticated: 30 search requests/minute → completes in ~9 minutes for 265 teams
- Always add `time.sleep(2.5)` between search requests regardless
- Handle 429 responses with **exponential backoff**: on a 429, sleep for `2^attempt * 5` seconds (5s, 10s, 20s) before retrying. A simple `time.sleep(2.5)` is not enough if GitHub's secondary rate limiter triggers — it will keep returning 429 until you back off properly.

```python
def github_search_with_backoff(query, headers, max_retries=5):
    for attempt in range(max_retries):
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "updated", "order": "desc", "per_page": 10},
            headers=headers,
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (403, 429):
            wait = (2 ** attempt) * 5
            print(f"  Rate limited. Waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    return None  # exhausted retries
```

### 4.2 Repo Scoring System

For each search result (up to 10 per query), score it:

| Criterion | Points |
|-----------|--------|
| Repo name or description contains "devtrails" (case-insensitive) | +4 |
| Repo name or description contains "2026" | +2 |
| README.md content contains "guidewire" (case-insensitive) | +3 |
| Repo pushed within the last 6 months | +2 |
| Repo description contains team name (partial match) | +2 |
| Repo is a fork | -5 |
| Repo has 0 commits | -3 |
| Repo is archived | -4 |

> **[REVIEWER 3 NOTE — v1.3]** Changed "Repo pushed/created in 2025 or 2026" (+2) to "Repo pushed within the last 6 months" (+2). The original criterion matched almost every repo on GitHub since we're in 2026 — it gave +2 to false positives and real repos equally, making it a useless discriminator. "Within 6 months" is tight enough to filter out old unrelated repos while still covering active hackathon repos.

**Scoring outcome:**
- Score ≥ 5: `HIGH_CONFIDENCE` — clone and review normally
- Score 2–4: `LOW_CONFIDENCE` — clone and review, but flag in `low_confidence.txt` with score
- Score < 2 and results exist: take the top result anyway, mark `LOW_CONFIDENCE`
- No results at all: mark `NOT_FOUND` in `not_found.txt`

**Critical rule:** Never skip a team entirely unless there are literally zero GitHub results. A `LOW_CONFIDENCE` review with caveats is infinitely more useful than a blank. You will manually verify `low_confidence.txt` entries later.

### 4.3 README Pre-fetch

For each candidate repo before deciding final score, fetch the README:
```
GET https://api.github.com/repos/{owner}/{repo}/readme
```
Decode the base64 content. Search for: "guidewire", "devtrails", "hackathon". Add +3 to score if found.

This README fetch counts against rate limits so do it only for top 3 candidates per team, not all 10.

### 4.4 Output

Write a JSON file `repos_manifest.json`:
```json
[
  {
    "team_name": "Team Alpha",
    "safe_name": "Team Alpha",
    "repo_url": "https://github.com/user/repo",
    "confidence": "HIGH",
    "score": 8,
    "clone_path": "repos/Team Alpha",
    "clone_status": "pending",
    "review_status": "pending"
  }
]
```

`review_status` values: `pending` → `complete` → `failed`. Update to `complete` immediately after writing the `.md`. Update to `failed` after all retries are exhausted. On resume, skip any team where `review_status` is `complete`. This makes `repos_manifest.json` the single source of truth for the entire pipeline state — you never need to check the `reviews/` folder to know what's done.

### 4.5 Multi-Query Fallback for NOT_FOUND Teams (NEW — v1.3)

The primary query `"{team_name}" DEVTrails 2026` only finds repos where the team name appears in the repo name, description, or README. Teams that named their repo something unrelated (e.g., `my-project` instead of `teamname-devtrails`) will be missed. Run this fallback sequence before declaring a team NOT_FOUND:

**Fallback Query Sequence (run in order, stop at first result):**

```python
def search_with_fallbacks(team_name, headers):
    # Clean the team name for safe URL encoding
    safe_query_name = team_name.replace('"', '').strip()
    
    queries = [
        f'"{safe_query_name}" DEVTrails 2026',          # primary: exact name + event
        f'"{safe_query_name}" DEVTrails',                # drop year (some skip it)
        f'"{safe_query_name}" guidewire hackathon',      # drop event name entirely
        f'{safe_query_name} DEVTrails 2026',             # no quotes (for multi-word names)
    ]
    
    for i, query in enumerate(queries):
        result = github_search_with_backoff(query, headers)
        if result and result.get('total_count', 0) > 0:
            print(f"  Found on fallback query {i+1}: {query}")
            return result, i  # return result + which fallback was used
        time.sleep(2.5)
    
    return None, -1  # truly not found
```

**GitHub Code Search (last resort):**
If all repository searches fail, try the code search API which searches inside file contents:
```python
def code_search_fallback(team_name, headers):
    """Search inside file contents — finds repos where team name is only in source code."""
    query = f'"{team_name}" "DEVTrails" language:markdown'
    resp = requests.get(
        "https://api.github.com/search/code",
        params={"q": query, "per_page": 5},
        headers=headers,
        timeout=30
    )
    if resp.status_code == 200:
        items = resp.json().get('items', [])
        if items:
            # Extract unique repos from code search results
            repos = list({item['repository']['full_name']: item['repository'] 
                         for item in items}.values())
            return repos
    return []
```

Note: Code search has a separate rate limit (10 requests/minute authenticated). Use it only for NOT_FOUND teams to stay within limits.

**Record the fallback level used:** Add a `search_fallback_level` field (0=primary, 1-3=fallback queries, 4=code search) to `repos_manifest.json` so you know later how reliable each discovery was.

### 4.6 NOT_FOUND Manual Recovery Workflow (NEW — v1.3)

After the automated pipeline, you will likely have 10-40 NOT_FOUND teams. Do not ignore these — each one is a blind spot in your intelligence. Manual recovery process:

1. Open `not_found.txt`. For each team name:
2. Go to `github.com/search?q=DEVTrails+2026&type=repositories` and manually search for variations of the team name.
3. Check the DEVTrails official submission portal (if public) — many hackathons link repos on submission pages.
4. Check if the hackathon has a public Discord/Slack — team announcements sometimes include repo links.
5. If still not found after 5 minutes: write a placeholder `reviews/{team_name}.md` with `## Status: REPO NOT FOUND` and move on. A NOT_FOUND entry in the synthesis is still useful data (it means this team likely has a weaker or non-existent public implementation).

---

## 5. Phase 2 — Repository Cloning

**Script:** `src/02_clone_repos.py`

### 5.1 Shallow Clone

```bash
git clone --depth 1 --single-branch {repo_url} "repos/{team_name}/"
```

`--depth 1`: Only the latest commit. You don't need history.
`--single-branch`: Only the default branch. Saves time and disk.

### 5.2 Size Guard

Before cloning, check repo size from the GitHub API (`repo.size` field in the search result, measured in KB). If size > 500MB, do a sparse checkout instead:

```bash
git clone --depth 1 --filter=blob:none --sparse {repo_url} "repos/{team_name}/"
cd "repos/{team_name}/"
git sparse-checkout set src lib core app backend api frontend
```

This pulls only the folders most likely to contain code, skipping large assets.

### 5.3 Empty Repo Detection

After cloning, check if the repo has any code files:
```python
code_extensions = {'.py', '.js', '.ts', '.java', '.cs', '.go', '.rb', '.rs', '.cpp', '.c', '.kt', '.swift'}
code_files = [f for f in Path(clone_path).rglob('*') if f.suffix in code_extensions]
if len(code_files) == 0:
    # Write minimal .md and skip to next team
```

### 5.4 Resumability

Check if `repos/{team_name}/.git` already exists before cloning. If it does, skip. This makes the script resumable.

### 5.5 Clone Manifest Update

After cloning, update `repos_manifest.json` with:
- `clone_status`: "success", "empty", "sparse", "failed"
- `file_count`: total code files found
- `repo_size_kb`: actual size on disk

---

## 6. Phase 3 — Deep Code Review Engine

**Script:** `src/03_review_repos.py`

This is the most critical phase. Every design decision here has been made to maximise `.md` file quality for small Ollama models.

### 6.1 Resumability First

At the start of processing each team:
```python
review_path = Path(f"reviews/{team_name}.md")
if review_path.exists():
    print(f"Skipping {team_name} — review already exists")
    continue
```
This is non-negotiable. The pipeline must be killable and restartable without losing work.

### 6.2 File Walker

The walker builds a categorised manifest of every file. Classification logic:

**Step 1: Skip these unconditionally**
```python
SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv', 
    'env', 'dist', 'build', '.next', 'vendor', 'target',
    '.gradle', 'obj', 'bin'
}
SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.pdf', '.zip', '.tar', '.gz', '.jar', '.war', '.lock',
    '.sum', '.snap', '.map', '.min.js', '.min.css'
}
```

**Step 2: Classify files into categories**
Classification is done by path and filename — order matters, first match wins:

```python
CATEGORIES = [
    ('config', [
        lambda f: f.name in {'package.json', 'requirements.txt', 'pom.xml', 
                              'go.mod', 'Cargo.toml', 'build.gradle', 
                              'Dockerfile', 'docker-compose.yml', 
                              'docker-compose.yaml', '.env.example',
                              'pyproject.toml', 'setup.py', 'setup.cfg',
                              'application.yml', 'application.yaml',
                              'application.properties', 'config.yaml',
                              'config.json', 'tsconfig.json', 'webpack.config.js'}
    ]),
    ('entrypoint', [
        lambda f: f.name in {'main.py', 'app.py', 'server.py', 'index.js',
                              'index.ts', 'app.js', 'server.js', 'server.ts',
                              'main.go', 'main.java', 'Program.cs', 'main.rs',
                              'index.php', 'application.py'}
    ]),
    ('readme', [
        lambda f: f.name.lower().startswith('readme')
    ]),
    ('data_model', [
        lambda f: any(kw in f.name.lower() for kw in 
                     ['model', 'schema', 'entity', 'db', 'database', 
                      'migration', 'migrate', 'orm']),
        lambda f: any(kw in str(f).lower() for kw in 
                     ['/models/', '/schemas/', '/entities/', '/db/'])
    ]),
    ('api', [
        lambda f: any(kw in str(f).lower() for kw in 
                     ['/api/', '/routes/', '/controllers/', '/handlers/', 
                      '/endpoints/', '/views/', '/resources/'])
    ]),
    ('core_logic', [
        lambda f: any(kw in str(f).lower() for kw in 
                     ['/src/', '/lib/', '/core/', '/services/', '/backend/',
                      '/business/', '/domain/', '/logic/', '/utils/', '/helpers/'])
    ]),
    ('frontend', [
        lambda f: any(kw in str(f).lower() for kw in 
                     ['/frontend/', '/ui/', '/client/', '/pages/', 
                      '/components/', '/views/', '/web/'])
    ]),
    ('infra', [
        lambda f: any(kw in str(f).lower() for kw in 
                     ['/infra/', '/k8s/', '/terraform/', '/deploy/', 
                      '/helm/', '/ansible/'])
    ]),
    ('tests', [
        lambda f: any(kw in str(f).lower() for kw in 
                     ['/test/', '/tests/', '/spec/', '/__tests__/', '/testing/'])
    ]),
]
```

**Flat repo fallback:** If after classification fewer than 3 files are assigned to named categories (indicating a flat or unconventional structure), reclassify ALL files as `core_logic`. This ensures you don't miss implementations in repos that don't follow standard conventions.

**Large file handling:** If a file is over 100KB, do NOT skip it. Instead, chunk it by lines:
```python
MAX_FILE_CHARS = 80_000  # ~20K tokens, safe for 32K context models
if len(content) > MAX_FILE_CHARS:
    chunks = [content[i:i+MAX_FILE_CHARS] 
              for i in range(0, len(content), MAX_FILE_CHARS)]
    return [(f"{filepath} [part {i+1}/{len(chunks)}]", chunk) 
            for i, chunk in enumerate(chunks)]
```

**Per-team chunk cap (NEW — v1.3):** Add `MAX_CHUNKS_PER_TEAM = 20` in `config.py`. If a repo generates more than 20 chunks (indicating an unusually large codebase), process the first 20 chunks in priority order (config → readme → data_model → entrypoint → core_logic → api → frontend), log a warning, and proceed to assembly. Without this cap, a single large repo could take 2+ hours and stall the entire run. 20 chunks × 20s per call = ~7 minutes max per team, which is acceptable.

### 6.3 The Smart Chunker

Groups the classified files into prompts. Each prompt must stay under `MAX_CHUNK_CHARS` (configurable, default 60,000 characters of code — leaves room for the prompt template).

**Grouping order (critical — builds context progressively):**
1. config
2. readme
3. data_model
4. entrypoint
5. core_logic (may generate multiple chunks if large)
6. api
7. frontend
8. infra
9. tests

For each group, concatenate files with clear separators:
```
=== FILE: src/models/user.py ===
{file_content}

=== FILE: src/models/policy.py ===
{file_content}
```

If a group exceeds `MAX_CHUNK_CHARS`, split it into multiple chunks and label them "part 1 of N".

### 6.4 Context Chaining Between Chunks

This is crucial for small models. Every chunk prompt after the first one includes a "prior context" section at the top:

```
PRIOR ANALYSIS CONTEXT (from earlier chunks of the same repo):
{accumulated_summary_so_far}

Now analyse this new chunk:
```

`accumulated_summary_so_far` is the concatenation of all previous chunk summaries (not the raw code — summaries are small). This lets the model connect `db.session.add(user)` in a route file to the SQLAlchemy model it saw earlier.

**Context budget warning:** Each chunk prompt consumes roughly: 500 tokens (prompt template) + 15,000 tokens (60K chars of code) + N×500 tokens (accumulated prior context summaries). With num_ctx=32768, you have headroom until about chunk 30. In practice with the 20-chunk cap, you will never overflow. However: the **assembly call** concatenates ALL chunk summaries. If 20 chunks each produce a 400-token summary, that's 8,000 tokens of summaries + 500 tokens file tree + 1,000 tokens prompt = ~9,500 tokens for the assembly call. This is safe. If you remove the 20-chunk cap, monitor the assembly call token count.

### 6.5 Per-Chunk Prompt

```
You are a precise technical code analyst. Your job is to extract what is EXPLICITLY present 
in the code. Do NOT infer, guess, or add context not visible in the code.
For any section where you find nothing: write exactly "NOT FOUND".
If code comments or documentation are in a non-English language, note the language 
and still extract the technical structure.

TEAM: {team_name}
CHUNK TYPE: {category} files — chunk {chunk_num} of {total_chunks}

{prior_context_if_any}

=== CODE ===
{file_contents}
=== END CODE ===

Answer ALL sections below. Be specific — use actual names, not generic descriptions.

TECH_STACK:
List every framework, library, language, and tool you can see imported, configured, 
or referenced. Include version numbers if visible. One item per line.

PURPOSE:
For each file in this chunk, one sentence describing what it does.
Format: filename.ext → what it does

KEY_FUNCTIONS:
List the 5-10 most important function, method, or class names.
Format: name() → what it does in one sentence

DATA_STRUCTURES:
List every class, interface, schema, struct, or data model defined.
Format: ClassName → fields: field1 (type), field2 (type)

EXTERNAL_INTEGRATIONS:
Any external API calls, database connections, message queues, third-party services.
Include URLs, hostnames, or service names if visible.

GUIDEWIRE_SPECIFIC:
Any Guidewire API endpoints, ClaimCenter/PolicyCenter/BillingCenter references, 
Guidewire data models, or Guidewire-specific patterns. VERY IMPORTANT.

UNUSUAL_PATTERNS:
Anything architecturally interesting, clever, or uncommon. If nothing: write NONE.

COMPLETENESS:
How complete does this section of code appear? Low / Medium / High. One sentence explaining why.
```

### 6.6 Assembly Prompt (Final Step Per Team)

After all chunks are reviewed, generate the repo file tree, then run the assembly call:

```python
def generate_file_tree(clone_path: Path, max_lines=150) -> str:
    """Generate a compact file tree for the assembly prompt's structural context."""
    lines = []
    for f in sorted(clone_path.rglob('*')):
        if any(skip in f.parts for skip in SKIP_DIRS):
            continue
        indent = '  ' * (len(f.relative_to(clone_path).parts) - 1)
        lines.append(f"{indent}{f.name}{'/' if f.is_dir() else ''}")
    return '\n'.join(lines[:max_lines])  # cap to avoid bloating the prompt
```

Pass the result as `{repo_file_tree}` in the assembly prompt below. It gives the model structural awareness of the full project even for files that weren't in any chunk.

After all chunks are reviewed, run a final assembly call to merge everything into the structured `.md`:

```
You are writing a technical intelligence report for a hackathon analysis system.
Below are analysis summaries of different code sections from one team's repository.
Your job: synthesise them into one structured report.

RULES:
- Only include information that appears in the summaries below
- Do NOT add, infer, or guess anything
- Use the EXACT section headers shown in the output format
- If a section has no information from the summaries, write: NOT FOUND

TEAM: {team_name}
REPO URL: {repo_url}
CONFIDENCE: {confidence_level}

FILE TREE (for structural context):
{repo_file_tree}  ← include this always — it gives the model structural awareness

SUMMARIES FROM ALL CHUNKS:
{all_chunk_summaries_concatenated}

Write the report in EXACTLY this format with EXACTLY these headers:

# {team_name}

**Repo:** {repo_url}  
**Confidence:** {confidence_level}  
**Review Date:** {date}

---

## Tech Stack
[bullet list — every technology identified]

## Architecture Overview
[3-5 sentences describing how the system is structured, data flows, main components]

## Core Features Implemented
[bullet list — what the app actually DOES, based on code evidence]

## Data Models
[for each model: name → key fields with types]

## API Surface
[list of endpoints, service methods, or RPC calls found]
[format: METHOD /path → what it does]

## Guidewire Integration
[specific Guidewire APIs, centers, or data structures used — VERY IMPORTANT]
[If nothing found: NOT FOUND]

## External Integrations
[list of external services, databases, APIs]

## Notable Technical Choices
[architecturally interesting decisions — the rare and clever stuff]
[If nothing: Standard implementation]

## Completeness Assessment
**Level:** [Low / Medium / High]  
**Reasoning:** [2-3 sentences on what works and what's clearly missing]

## What Is Missing or Incomplete
[list of obvious gaps: stubbed features, TODO comments, missing endpoints]

## Replication Notes
[what you would need to build a replica: key algorithms, data flow, dependencies]
[This section should be detailed enough to actually rebuild the project]
```

**Assembly call uses `num_predict=8192`** — see Section 8.4 and 8.5 for implementation. Do not forget this. The default 4096 will truncate the output silently, especially the Replication Notes section which is the most valuable.

### 6.7 Output Validation

After writing each `.md` file, run a validator:

```python
REQUIRED_SECTIONS = [
    '## Tech Stack',
    '## Architecture Overview', 
    '## Core Features Implemented',
    '## Data Models',
    '## API Surface',
    '## Guidewire Integration',
    '## External Integrations',
    '## Notable Technical Choices',
    '## Completeness Assessment',
    '## What Is Missing or Incomplete',
    '## Replication Notes',
]

def validate_review(filepath):
    content = Path(filepath).read_text()
    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    # BUG FIX (v1.3): Previous version used content.split(s)[1] which is fragile 
    # (splits on first occurrence, returns everything after including later sections).
    # Use the already-defined extract_section() function instead.
    all_not_found = all(
        extract_section(content, s).strip().upper().startswith('NOT FOUND')
        for s in REQUIRED_SECTIONS if s in content
    )
    if missing:
        return False, f"Missing sections: {missing}"
    if all_not_found:
        return False, "All sections are NOT FOUND — model likely failed"
    return True, "OK"
```

If validation fails: retry with a simplified prompt that just asks for the missing sections. If retry fails: write a `VALIDATION_FAILED` marker at the top of the `.md` so you can find it later.

### 6.8 Main Orchestration Loop for Phase 3 (NEW — v1.3)

The previous blueprint had all the components but never showed how they connect. This is the main loop that ties everything together — implement `03_review_repos.py` exactly like this:

```python
# src/03_review_repos.py — Main orchestration loop
import json
from pathlib import Path
from utils.file_walker import walk_and_classify
from utils.chunker import chunk_files
from utils.ollama_client import ollama_generate, ollama_generate_with_retry
from utils.validator import validate_review, REQUIRED_SECTIONS
from utils.file_walker import generate_file_tree
from config import *

def review_team(team_entry: dict):
    team_name = team_entry['team_name']
    safe_name = team_entry['safe_name']
    repo_url = team_entry['repo_url']
    confidence = team_entry['confidence']
    clone_path = Path(f"repos/{safe_name}")
    review_path = Path(f"reviews/{safe_name}.md")

    # Step 1: Resumability check
    if review_path.exists() or team_entry.get('review_status') == 'complete':
        print(f"[SKIP] {team_name} — already reviewed")
        return

    # Step 2: Walk and classify files
    classified = walk_and_classify(clone_path)  # returns {category: [Path, ...]}
    if not classified:
        write_empty_review(review_path, team_name, repo_url, "EMPTY REPO")
        return

    # Step 3: Chunk files in processing order
    chunks = chunk_files(classified, MAX_CHUNK_CHARS, MAX_CHUNKS_PER_TEAM)
    # chunks = [(category, chunk_num, total_chunks, [(filepath, content), ...])]

    # Step 4: Per-chunk Ollama calls with context chaining
    chunk_summaries = []
    accumulated_context = ""
    for category, chunk_num, total_chunks, file_list in chunks:
        file_content_block = "\n\n".join(
            f"=== FILE: {fp} ===\n{content}" for fp, content in file_list
        )
        prior_context_block = (
            f"PRIOR ANALYSIS CONTEXT (from earlier chunks of the same repo):\n{accumulated_context}\n\nNow analyse this new chunk:\n"
            if accumulated_context else ""
        )
        prompt = build_chunk_prompt(team_name, category, chunk_num, total_chunks,
                                     prior_context_block, file_content_block)
        summary = ollama_generate_with_retry(prompt, CODE_REVIEW_MODEL)
        if summary:
            chunk_summaries.append(summary)
            accumulated_context += f"\n---\nCHUNK {chunk_num} ({category}):\n{summary}"
        else:
            chunk_summaries.append(f"CHUNK {chunk_num} ({category}): FAILED TO PROCESS")
        print(f"  [{team_name}] Chunk {chunk_num}/{total_chunks} done")

    # Step 5: Assembly call (with num_predict=8192)
    file_tree = generate_file_tree(clone_path)
    all_summaries = "\n\n---\n\n".join(chunk_summaries)
    assembly_prompt = build_assembly_prompt(team_name, repo_url, confidence,
                                             file_tree, all_summaries)
    md_content = ollama_generate(assembly_prompt, CODE_REVIEW_MODEL,
                                  temperature=0.1, num_predict=8192)  # ← 8192, not 4096

    if not md_content:
        write_failed_review(review_path, team_name)
        update_manifest_status(team_entry, 'failed')
        return

    # Step 6: Validate and write
    review_path.write_text(md_content, encoding='utf-8')
    valid, reason = validate_review(review_path)
    if not valid:
        print(f"  [{team_name}] Validation failed: {reason} — retrying missing sections...")
        md_content = retry_missing_sections(md_content, review_path, team_name,
                                             repo_url, all_summaries)
    
    update_manifest_status(team_entry, 'complete')
    print(f"  [{team_name}] Done ✓")


def main():
    manifest = json.loads(Path('repos_manifest.json').read_text())
    
    # Process in priority order: HIGH first, then LOW, then handle NOT_FOUND last
    ordered = (
        [t for t in manifest if t['confidence'] == 'HIGH'] +
        [t for t in manifest if t['confidence'] == 'LOW'] +
        [t for t in manifest if t['confidence'] == 'NOT_FOUND']
    )
    
    # Within HIGH_CONFIDENCE, sort by most recently pushed (active repos first)
    # repo activity data was stored in manifest during Phase 1
    
    for i, team_entry in enumerate(ordered):
        print(f"\n[{i+1}/{len(ordered)}] Processing: {team_entry['team_name']}")
        try:
            review_team(team_entry)
        except Exception as e:
            print(f"  ERROR on {team_entry['team_name']}: {e}")
            update_manifest_status(team_entry, 'failed')
            continue

if __name__ == '__main__':
    main()
```

---

## 7. Phase 4 — Knowledge Synthesis

**Script:** `src/04_synthesize.py`

### 7.1 Code-Driven Frequency Analysis (Python, No LLM)

Parse all 265 `.md` files in Python. Extract each section's content. Build frequency dictionaries.

```python
from pathlib import Path
import re
from collections import Counter

def extract_section(md_content, section_header):
    """Extract content between section_header and the next ## header"""
    pattern = rf'{re.escape(section_header)}\n(.*?)(?=\n## |\Z)'
    match = re.search(pattern, md_content, re.DOTALL)
    return match.group(1).strip() if match else ''

# Parse all reviews
tech_stacks = []
notable_choices = []
features = []
guidewire_apis = []

for md_file in Path('reviews').glob('*.md'):
    content = md_file.read_text()
    tech_stacks.append(extract_section(content, '## Tech Stack'))
    notable_choices.append(extract_section(content, '## Notable Technical Choices'))
    features.append(extract_section(content, '## Core Features Implemented'))
    guidewire_apis.append(extract_section(content, '## Guidewire Integration'))
```

Then extract individual technologies from tech stack sections using a known-technology lookup list (seeded with common frameworks: React, FastAPI, Spring Boot, etc.) plus a regex for bullet items. This gives you real counts, not LLM-guessed counts.

**Output:** A Python dict like:
```python
{
    'React': 187,
    'FastAPI': 143,
    'Spring Boot': 41,
    'PostgreSQL': 118,
    ...
}
```

**Also extract from `## Guidewire Integration` and `## API Surface` (NEW — v1.3):**
These two sections are the most strategically valuable for gap analysis in a Guidewire hackathon. Extract them with the same frequency method:

```python
# Guidewire-specific keyword extraction
GUIDEWIRE_KEYWORDS = [
    'ClaimCenter', 'PolicyCenter', 'BillingCenter', 'ContactManager',
    'InsuranceSuite', 'Cloud API', 'Integration Framework', 'Gosu',
    'OOTB', 'PCF', 'Guidewire Cloud', 'Data Platform', 'Jutro',
    'AppExchange', 'Predictive Analytics', 'Cyence'
]

guidewire_freq = Counter()
for section in guidewire_apis:
    if section and section.strip().upper() != 'NOT FOUND':
        for kw in GUIDEWIRE_KEYWORDS:
            if kw.lower() in section.lower():
                guidewire_freq[kw] += 1

# This tells you which Guidewire products/APIs are used by how many teams.
# Low-frequency Guidewire integration = your biggest differentiation opportunity.
```

### 7.2 MASTER_PATTERNS.md Generation

Use Ollama (mistral:7b) to interpret the frequency data — but feed it the Python-computed numbers, not raw text:

```
Here are the technology usage frequencies across 265 DEVTrails 2026 hackathon teams.
These counts are exact — computed by code, not estimated.

TECH STACK FREQUENCIES:
{json.dumps(tech_freq, indent=2)}

FEATURE FREQUENCIES (approximate, from text analysis):
{json.dumps(feature_freq, indent=2)}

GUIDEWIRE API USAGE:
{json.dumps(guidewire_freq, indent=2)}

Write MASTER_PATTERNS.md with these sections:
1. Table stakes (used by >60% of teams — avoid differentiating on these)
2. Common choices (used by 30-60% of teams)
3. Minority choices (used by 10-30% of teams)
4. Guidewire API coverage (which APIs appear most and least often)
5. Estimated average completeness level across all teams
```

### 7.3 GAPS.md — Code-Driven, LLM-Interpreted

**Step 1 (Python):** Extract from THREE sections — `## Notable Technical Choices`, `## Guidewire Integration`, and `## API Surface`. Tokenize into bullet items. Count frequency. Exclude any item where the frequency of matching technologies is above 15% of teams (too common to be a gap).

> **[REVIEWER 3 NOTE — v1.3]** Previous version only mined `## Notable Technical Choices` for gaps. This misses the most valuable signal: rare Guidewire API usage. A team using `Jutro` (Guidewire's UI framework) when only 3% of teams use it is a massive gap. Mining `## Guidewire Integration` and `## API Surface` alongside Notable Technical Choices captures this. Rare = differentiating.

**Step 2 (Ollama):** Feed the low-frequency items to the model for interpretation:

```
Below are technical implementation choices that appear in fewer than 15% of DEVTrails 
2026 competing teams. These are potential differentiation opportunities.

LOW-FREQUENCY CHOICES (from Notable Technical Choices):
{rare_notable_items}

LOW-FREQUENCY GUIDEWIRE APIS (used by fewer than 15% of teams):
{rare_guidewire_items}

LOW-FREQUENCY API PATTERNS (from API Surface analysis):
{rare_api_patterns}

For each item:
1. Explain what it is in plain terms
2. Estimate implementation complexity: Low / Medium / High
3. Estimate potential hackathon judge impact: Low / Medium / High
4. Explain why it might be rare (hard to implement? niche? timing?)

Then write a final section: TOP 10 DIFFERENTIATION OPPORTUNITIES
ranked by (high impact × low/medium complexity)
```

### 7.4 YOUR_FEATURE_PLAN.md — Gemini Step

This step uses Gemini Pro (or Gemini Flash — doesn't matter, both have large context). By this point you have two small documents: `GAPS.md` and a description of your current repo state. Feed both to Gemini:

```
I am competing in the Guidewire DEVTrails 2026 hackathon. I have completed competitive 
intelligence analysis of all 265 competing teams.

HERE IS WHAT MOST TEAMS ARE NOT BUILDING (GAPS.md):
{gaps_md_content}

HERE IS MY CURRENT IMPLEMENTATION:
{your_repo_description}  ← write this manually, ~500 words describing what you've built

TASK: Suggest 5 high-impact features I should build in the next 24 hours that would 
make my submission clearly stand out from competitors.

For each feature:
- Feature name and description
- Why it's rare/innovative given the competition landscape  
- Estimated implementation time (be realistic for a solo developer)
- Specific technical approach (not generic — give actual implementation guidance)
- Which part of my existing implementation it extends

Rank by: (uniqueness in competition) × (feasibility in 24h) / (implementation complexity)
```

---

## 8. Prompt Architecture (Critical)

### 8.1 Why Prompts Are the Bottleneck

Small models (7B, 14B) fail in two ways:
1. **Hallucination** — they invent details not in the code
2. **Format collapse** — they stop following the output structure partway through

Both are mitigated by prompt design, not by the model itself.

### 8.2 Anti-Hallucination Rules

Every prompt must contain:
- "Extract ONLY what is explicitly present in the code"
- "Do NOT infer, guess, or add context not visible in the code"  
- "If something is not found, write: NOT FOUND"

Never ask a small model open-ended questions like "what could this system do?" — ask closed questions like "what functions are defined in this file?"

### 8.3 Anti-Format-Collapse Rules

- Use ALL-CAPS section headers in prompts (`TECH_STACK:` not `Tech Stack:`)
- Put the output format instructions at the END of the prompt, not the beginning
- Use simple formats — bullet lists, not tables. Small models struggle to produce well-formed markdown tables
- Keep total prompt length (instruction + code + prior context) under 20,000 tokens. If you exceed this, split the code chunk, not the instructions.

### 8.4 Ollama Client Configuration

```python
import requests

def ollama_generate(prompt, model, temperature=0.1, num_ctx=32768, num_predict=4096):
    """
    temperature=0.1: Low temperature for factual extraction (not creative tasks)
    num_ctx: Set to model's max context window
    num_predict: Default 4096 for chunk calls. Pass 8192 explicitly for assembly calls.
    """
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": num_predict,  # ← parameter, not hardcoded
                "repeat_penalty": 1.1,  # Prevents repetition loops
                "stop": ["<|im_end|>", "### END", "---END---"]
            }
        },
        timeout=300  # 5 minute timeout per call
    )
    return response.json()['response']
```

### 8.5 Retry Logic

```python
def ollama_generate_with_retry(prompt, model, max_retries=3, num_predict=4096):
    for attempt in range(max_retries):
        try:
            result = ollama_generate(prompt, model, num_predict=num_predict)
            if len(result.strip()) > 100:  # Basic sanity check
                return result
            print(f"  Attempt {attempt+1}: Response too short, retrying...")
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(10)
    return None  # Caller handles None as failure

def ollama_assembly_call(prompt, model):
    """
    Assembly calls MUST use num_predict=8192.
    The assembly output (full .md with Replication Notes) regularly exceeds 4096 tokens
    and will be silently truncated at the default value. There is no error — the file
    just ends mid-sentence. This is one of the hardest bugs to spot after a full run.
    
    BUG FIX (v1.3): Previous version had a comment saying "call ollama_generate directly
    with that override" but the function body still called ollama_generate_with_retry
    WITHOUT passing num_predict=8192. This function now correctly passes it.
    """
    return ollama_generate_with_retry(prompt, model, max_retries=3, num_predict=8192)
```

---

## 9. Ollama Model Selection

### Primary Code Review Model: `qwen2.5-coder:14b`

Pull command: `ollama pull qwen2.5-coder:14b`

Why: Specifically trained on code. Dramatically outperforms general models at extracting technical structure from unfamiliar codebases. The 14B variant is worth the RAM — it produces substantially more accurate function/class extraction than 7B.

Context window: 32K tokens. Set `num_ctx=32768` in all calls.

RAM required: ~9GB VRAM for GPU inference, ~12GB RAM for CPU inference.

### Fallback Code Review Model: `qwen2.5-coder:7b`

If 14B won't run on your hardware, use 7B. Quality drops but it's usable.

Pull command: `ollama pull qwen2.5-coder:7b`

### Synthesis Model: `mistral:7b`

Pull command: `ollama pull mistral:7b`

Why: Better at text summarisation and pattern analysis than coder models. Used only in Phase 4 where input is already-processed text, not raw code.

### Model Memory Management Between Phases (NEW — v1.3)

Your RTX 4090 Laptop has 16GB VRAM. `qwen2.5-coder:14b` occupies ~9GB. `mistral:7b` occupies ~5GB. Ollama **keeps models loaded in VRAM** between calls. When you finish Phase 3 and start Phase 4, if you just call `mistral:7b` without explicitly unloading `qwen2.5-coder:14b`, Ollama will try to hold both models simultaneously (14GB combined), which exceeds your 16GB VRAM and forces it to offload layers to RAM — dramatically slowing Phase 4 synthesis.

**Fix: Explicitly unload Phase 3 model before starting Phase 4:**
```python
# At the end of 03_review_repos.py, or at the start of 04_synthesize.py:
import requests

def unload_model(model_name):
    """Force Ollama to release a model from VRAM."""
    requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model_name, "keep_alive": 0},  # keep_alive=0 unloads immediately
        timeout=30
    )
    print(f"Unloaded {model_name} from VRAM")

# Call before switching models:
unload_model(CODE_REVIEW_MODEL)  # free 9GB before loading mistral:7b
```

### Feature Planning: Gemini Pro (Cloud)

Used only once, for `YOUR_FEATURE_PLAN.md`. Input by this point is ~3000 words of pre-processed analysis. Well within Gemini's context window.

---

## 10. Failure Modes and Mitigations

| Failure Mode | Detection | Mitigation |
|---|---|---|
| GitHub rate limit | HTTP 403 or 429 response | Exponential backoff (Section 4.1) + token auth |
| Repo not found | Zero search results on all fallback queries | Multi-query fallback (Section 4.5) → manual recovery (Section 4.6) |
| Wrong repo found | Low confidence score | Log to `low_confidence.txt`, review but flag |
| Empty repo | Zero code files after clone | Write minimal `.md` noting "EMPTY REPO" |
| Huge repo | `repo.size > 500000` in API | Sparse checkout |
| Flat/nonstandard structure | <3 files classified | Reclassify all files as `core_logic` |
| Large single file | File size > 100KB | Line-chunk into sub-files, send separately |
| Too many chunks | Chunks > MAX_CHUNKS_PER_TEAM | Cap at 20, log warning, proceed to assembly |
| Ollama response truncated | Response length < 100 chars | Retry up to 3 times with backoff |
| Assembly output truncated | Review ends mid-sentence | Use num_predict=8192 for assembly calls (Section 8.5) |
| All sections return NOT FOUND | Validator catches this | Retry with simpler single-section prompts |
| Ollama crashes mid-run | Exception in API call | Resumability check at top of each team |
| Disk space exhaustion | Monitor during cloning | Limit to 500MB per repo, delete repos after review |
| Non-English code | Unusual characters in output | Add "note the language" instruction to prompt |
| Model repetition loop | Output contains repeated tokens | `repeat_penalty=1.1` in ollama options |
| VRAM pressure when switching models | Phase 4 inference very slow | Unload Phase 3 model explicitly (Section 9) |

### 10.1 Disk Management Strategy

After generating `reviews/{team_name}.md`, optionally delete the cloned repo:
```python
if DELETE_REPOS_AFTER_REVIEW:  # configurable in config.py
    shutil.rmtree(f"repos/{team_name}/")
```
This keeps disk usage flat — you only ever have a few repos on disk at once.

### 10.2 Re-review Mode

Build a mode into `03_review_repos.py` that accepts a section name and re-runs only that section against all 265 repos, patching the existing `.md` files:

```bash
python src/03_review_repos.py --rerun-section "Guidewire Integration"
```

This is essential for when you realise after batch completion that you consistently missed something.

---

## 11. Execution Order and Run Strategy

### 11.1 Full Run

```bash
python run_all.py
```

Internally runs:
1. `01_search_repos.py` — ~9 minutes for 265 teams
2. `02_clone_repos.py` — ~20-40 minutes depending on repo sizes
3. `03_review_repos.py` — the long step: 265 teams × ~6 Ollama calls × ~20s each = **~7–8 hours total**. Run overnight.
4. `04_synthesize.py` — ~1-2 hours

### 11.2 Phase 3 Time Analysis

**Parallel processing:** Ollama on GPU (RTX 4090 Laptop, 16GB VRAM) runs one inference at a time — it queues requests, it does not run them concurrently. `ThreadPoolExecutor` for Ollama calls does nothing except waste memory and create contention. **Do not parallelise Ollama calls.**

What you CAN parallelise:
- Phase 2 git cloning: pure I/O, use `max_workers=10`
- Phase 3 file walking and chunking (the Python prep before the Ollama call): fine to parallelise

The actual time estimate on a 4090 Laptop with `qwen2.5-coder:14b` fully loaded in VRAM:
- ~15–25 seconds per Ollama call
- ~6 calls per team × 265 teams = ~26,500 seconds sequential → **~7–8 hours total**

This is acceptable. Run it overnight. Do not attempt to "optimise" with workers — it will not help and may cause Ollama to crash under queue pressure.

**Skip test and infra files:** Tests and infra rarely contain the signal you care about. Make these optional with a config flag `SKIP_TEST_FILES=False` to cut processing time.

**Cache chunk summaries:** If a `.md` file exists, you've already processed the team. But also cache intermediate chunk summaries to a `cache/` folder — if you need to re-run the assembly step (e.g. to fix the assembly prompt), you don't need to re-run all the chunk prompts.

### 11.3 Validation Run

After Phase 3 completes:
```bash
python src/03_review_repos.py --validate-only
```
Prints a summary: how many passed, how many need retry, which sections are most commonly NOT FOUND.

### 11.4 Prioritised Processing

Don't process alphabetically. Prioritise in this order:
1. `HIGH_CONFIDENCE` repos first (most likely to yield useful reviews)
2. `LOW_CONFIDENCE` repos second
3. `NOT_FOUND` teams last (manual handling anyway)

Within HIGH_CONFIDENCE, prioritise by repo activity (most recent push date) — active repos are more likely to have substantial implementations worth analysing.

### 11.5 Progress Dashboard (NEW — v1.3)

After an overnight run, you need a fast way to check status without reading `repos_manifest.json` manually. Add `src/05_dashboard.py`:

```python
# src/05_dashboard.py — run at any time to check pipeline status
import json
from pathlib import Path
from collections import Counter

manifest = json.loads(Path('repos_manifest.json').read_text())

clone_statuses = Counter(t.get('clone_status', 'unknown') for t in manifest)
review_statuses = Counter(t.get('review_status', 'unknown') for t in manifest)
confidences = Counter(t.get('confidence', 'unknown') for t in manifest)

print("=" * 50)
print(f"TOTAL TEAMS: {len(manifest)}")
print()
print("REPO DISCOVERY:")
for k, v in confidences.items():
    print(f"  {k}: {v}")
print()
print("CLONE STATUS:")
for k, v in clone_statuses.items():
    print(f"  {k}: {v}")
print()
print("REVIEW STATUS:")
for k, v in review_statuses.items():
    print(f"  {k}: {v}")
print()

# Show teams still pending (need manual attention)
failed = [t['team_name'] for t in manifest if t.get('review_status') == 'failed']
if failed:
    print(f"FAILED REVIEWS ({len(failed)}):")
    for name in failed:
        print(f"  - {name}")
print("=" * 50)
```

Run this any time: `python src/05_dashboard.py`

---

## 12. config.py Reference

```python
# GitHub
GITHUB_TOKEN = "ghp_your_token_here"
GITHUB_SEARCH_DELAY = 2.5  # seconds between search requests

# Ollama
OLLAMA_BASE_URL = "http://localhost:11434"
CODE_REVIEW_MODEL = "qwen2.5-coder:14b"
SYNTHESIS_MODEL = "mistral:7b"

# File walker
MAX_CHUNK_CHARS = 60_000          # max code chars per Ollama call
MAX_FILE_CHARS = 80_000           # files over this get line-chunked
MAX_CHUNKS_PER_TEAM = 20          # NEW v1.3: cap to bound worst-case time per team
SKIP_TEST_FILES = False           # set True to speed up, False for completeness
DELETE_REPOS_AFTER_REVIEW = False # set True to save disk space

# Repo scoring
HIGH_CONFIDENCE_THRESHOLD = 5
LOW_CONFIDENCE_THRESHOLD = 2

# Misc
MAX_REPO_SIZE_KB = 500_000        # repos over 500MB get sparse checkout
# NOTE (v1.3): PARALLEL_WORKERS was previously set to 3 — this was a bug/contradiction.
# Section 11.2 explicitly says DO NOT parallelise Ollama calls.
# The only parallelism in this pipeline is for git cloning (I/O bound).
# These are now two separate, correctly-named constants:
CLONE_PARALLEL_WORKERS = 10       # for 02_clone_repos.py — safe, I/O bound
REVIEW_PARALLEL_WORKERS = 1       # for 03_review_repos.py — always 1, do not change
```

> **[REVIEWER 3 NOTE — v1.3]** The previous `PARALLEL_WORKERS = 3` in config.py directly contradicted Section 11.2 which says "Do NOT parallelise Ollama calls." An implementer copying this config would set workers=3 for Ollama, causing queue contention, possible Ollama crashes, and no speedup. Split into two clearly named constants so there's no ambiguity.

---

## 13. Quality Gates

Before moving from one phase to the next, check these:

### Gate 0→1 (after teams.txt)
- [ ] Exactly 265 lines
- [ ] No duplicate names
- [ ] File is UTF-8
- [ ] No blank lines

### Gate 1→2 (after repo search)
- [ ] `repos_manifest.json` has 265 entries
- [ ] At least 230 entries are HIGH or LOW confidence (>87% discovery rate)
- [ ] Not-found count < 35
- [ ] Manually spot-check 5 HIGH_CONFIDENCE entries to verify URLs are correct
- [ ] NEW: Check `search_fallback_level` distribution — if >50 teams needed fallback level 2+, your primary query may be wrong

### Gate 2→3 (after cloning)
- [ ] At least 220 repos cloned successfully
- [ ] Less than 10 empty repos
- [ ] Disk usage is manageable

### Gate 3→4 (after reviews)
- [ ] All 265 `.md` files exist (or have documented failure reasons)
- [ ] Validation pass rate > 90% (no more than 26 files failing structure check)
- [ ] No section is "NOT FOUND" in more than 50% of files (if it is, prompt has a bug)
- [ ] Spot-read 10 random `.md` files yourself — do they feel accurate and useful?
- [ ] Check that `## Guidewire Integration` has actual content in >50% of files
- [ ] NEW: Spot-check 3 assembly outputs for truncation — does `## Replication Notes` end naturally or mid-sentence? If truncated, num_predict=8192 was not applied correctly.

### Gate 4→done (after synthesis)
- [ ] `MASTER_PATTERNS.md` exists and has real frequency numbers
- [ ] `GAPS.md` has at least 10 actionable differentiation opportunities
- [ ] `GAPS.md` has at least 3 items from the Guidewire Integration section (not just Notable Technical Choices)
- [ ] `YOUR_FEATURE_PLAN.md` has 5 features with implementation guidance

---

## Reviewer Notes

> **[REVIEWER 1 — Claude Sonnet 4.6]**  
> Added from prior planning context:
> - Flat repo fallback (Section 6.2) — critical for hackathon codebases that don't follow conventions
> - Context chaining between chunks (Section 6.4) — small models need prior context hand-held
> - Code-driven frequency counting in Phase 4 before LLM interpretation (Section 7.1) — prevents hallucinated frequencies which would corrupt GAPS.md
> - Re-review mode (Section 10.2) — essential for iterative quality improvement
> - Parallel workers for Phase 3 (Section 11.2) — without this the timeline is infeasible
> - Quality gates (Section 13) — binary go/no-go checks before each phase transition
> - Guidewire Integration as its own mandatory section — this is the hackathon-specific signal most likely to differentiate winners; if you miss it across 265 repos you lose your biggest intelligence advantage
> - Low temperature (0.1) for all extraction calls — factual extraction, not creative generation
> - `repeat_penalty` in Ollama options — prevents output loops which corrupt `.md` files silently

> **[REVIEWER 2 — Claude Sonnet 4.6, hardware-aware pass]**  
> Six additions, zero deletions of existing content:
> - **Team name sanitization** (Section 3, new `name_sanitizer.py`): Characters like `/`, `:`, `*` in team names break all downstream file paths silently. `sanitize_name()` + `team_name_map.json` is the fix. Every path construction must go through `NAME_MAP[team_name]`. This was the most dangerous missing piece.
> - **`num_predict: 8192` for assembly calls** (Section 8.4): The assembly step writes full `.md` files including Replication Notes. 4096 tokens is not enough — output gets truncated silently with no error. `ollama_generate` now accepts `num_predict` as a parameter; assembly calls pass 8192.
> - **GPU parallelism correction** (Section 11.2): Rewrote based on confirmed hardware (RTX 4090 Laptop, 16GB VRAM). Ollama on GPU queues requests — `ThreadPoolExecutor` for Ollama calls does nothing. Actual estimate: ~7–8 hours sequential overnight run. Parallelism is still valid for git cloning (I/O bound, `max_workers=10`).
> - **File tree generation snippet** (Section 6.6): `{repo_file_tree}` was referenced in the assembly prompt but never implemented. Added `generate_file_tree()` with a 150-line cap to avoid bloating the prompt.
> - **`review_status` field in manifest** (Section 4.4): `repos_manifest.json` now tracks `pending/complete/failed` per team. On resume, check the manifest — don't scan the `reviews/` folder. Single source of truth.
> - **`00_collect_teams.py` documented** (Section 3, Option C): Was listed in the folder structure with no explanation. Added minimal `BeautifulSoup` scraper with a clear fallback note for auth-walled or JS-SPA leaderboards.

> **[REVIEWER 3 — Claude Sonnet 4.6, bug-fix and completeness pass]**  
> Four bugs fixed, one scoring criterion corrected, four missing pieces added. Full change log:
>
> **BUG FIXES (would have caused silent failures):**
> - **`name_sanitizer` collision counter bug** (Section 3): For 3+ teams mapping to the same safe name, the old `list(mapping.values()).count(safe)` logic produced duplicate safe names (e.g. both team B and C getting `X_1`). Fixed with a dedicated `defaultdict(int)` collision counter.
> - **`ollama_assembly_call` not actually passing `num_predict=8192`** (Section 8.5): The function body called `ollama_generate_with_retry` without the override parameter. Reviewer 2 added the concept but the implementation was broken. Fixed: `ollama_generate_with_retry` now accepts and forwards `num_predict`, and `ollama_assembly_call` explicitly passes 8192.
> - **`validate_review` using fragile `content.split(s)[1]`** (Section 6.7): This was inconsistent with the already-defined `extract_section()` function and would misread sections if headers appeared multiple times. Fixed to use `extract_section()`.
> - **`PARALLEL_WORKERS = 3` in config.py** (Section 12): Directly contradicted Section 11.2 ("Do NOT parallelise Ollama calls"). An implementer copying this config would set 3 Ollama workers, causing contention with no speedup. Replaced with `CLONE_PARALLEL_WORKERS = 10` and `REVIEW_PARALLEL_WORKERS = 1`.
>
> **SCORING CORRECTION:**
> - Changed "+2 for pushed/created in 2025 or 2026" to "+2 for pushed within last 6 months" (Section 4.2). The original criterion matched nearly every GitHub repo in existence by 2026, making it useless for discriminating hackathon repos from noise.
>
> **MISSING PIECES ADDED:**
> - **Multi-query fallback + NOT_FOUND recovery** (Sections 4.5, 4.6): The original pipeline had no plan B when primary search failed. Added 4-query fallback sequence + GitHub code search as last resort. Added manual recovery workflow for remaining NOT_FOUND teams. Without this, 20-40 teams become permanent blind spots.
> - **Per-team chunk cap `MAX_CHUNKS_PER_TEAM = 20`** (Section 6.2, config.py): No upper bound on chunks per team meant a single large repo could stall the pipeline for 2+ hours. 20-chunk cap bounds worst-case to ~7 minutes per team.
> - **Main Phase 3 orchestration loop** (Section 6.8): All components existed but their connection was never shown. Added the full `review_team()` + `main()` loop that ties file walking → chunking → per-chunk prompts → context chaining → assembly → validation → manifest update together. An implementer without this would have to guess the control flow.
> - **Ollama model memory management** (Section 9): On a 16GB VRAM laptop, `qwen2.5-coder:14b` (9GB) + `mistral:7b` (5GB) = 14GB. Without explicitly unloading Phase 3 model before Phase 4, Ollama holds both simultaneously and offloads to RAM, making synthesis very slow. Added `unload_model()` helper with the `keep_alive: 0` API call.
> - **Guidewire API frequency mining in synthesis** (Section 7.1, 7.3): GAPS.md previously only mined `## Notable Technical Choices`. In a Guidewire hackathon, rare Guidewire API usage is the highest-value differentiation signal. Added extraction from `## Guidewire Integration` and `## API Surface` with Guidewire-specific keyword list. Updated GAPS.md prompt to include these.
> - **Progress dashboard script** (Section 11.5): After a 7-8 hour overnight run you need a fast status check. Added `05_dashboard.py` showing clone/review/confidence distribution and failed team list.

---

*Pass this document to the next reviewer. Add your notes under the Reviewer Notes section. Increment the version number in the document title.*
