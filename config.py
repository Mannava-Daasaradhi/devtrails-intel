# =============================================================================
# config.py — DEVTrails 2026 Competitive Intelligence Pipeline
# Central configuration. Every script imports from here.
# =============================================================================
# SETUP REQUIRED:
#   1. Set GITHUB_TOKEN below (see README.md for how to create one)
#   2. Confirm OLLAMA_BASE_URL is correct (default: localhost:11434)
#   3. Confirm CODE_REVIEW_MODEL is pulled: `ollama pull qwen2.5-coder:14b`
#   4. Confirm SYNTHESIS_MODEL is pulled:   `ollama pull mistral:7b`
# =============================================================================

# -----------------------------------------------------------------------------
# GitHub
# -----------------------------------------------------------------------------

# Personal Access Token — create at: https://github.com/settings/tokens
# Scopes needed: none (public repo search works with any token)
# Without a token: 10 req/min → script works but is slow and fragile
# With a token:    30 req/min → completes in ~9 minutes for 265 teams
GITHUB_TOKEN = "ghp_your_token_here"

# Seconds to sleep between GitHub search requests.
# Keep at 2.5 even with a token — GitHub has a secondary rate limiter.
GITHUB_SEARCH_DELAY = 2.5

# Primary search query format. The {team_name} placeholder is filled per team.
# This is the first of 4 fallback queries — see 01_search_repos.py for the full sequence.
GITHUB_SEARCH_QUERY_TEMPLATE = '"{team_name}" DEVTrails 2026'

# README fetch: only pre-fetch README for top N candidates per team (saves API calls)
README_PREFETCH_TOP_N = 3

# -----------------------------------------------------------------------------
# Ollama
# -----------------------------------------------------------------------------

OLLAMA_BASE_URL = "http://localhost:11434"

# Code review model: used for all Phase 3 chunk + assembly calls
# qwen2.5-coder:14b is ~9GB VRAM — fits on RTX 4090 Laptop (16GB)
# Pull with: ollama pull qwen2.5-coder:14b
CODE_REVIEW_MODEL = "qwen2.5-coder:14b"

# Synthesis model: used for Phase 4 (MASTER_PATTERNS, GAPS, FEATURE_PLAN)
# mistral:7b is ~5GB VRAM — unload CODE_REVIEW_MODEL first (see 04_synthesize.py)
# Pull with: ollama pull mistral:7b
SYNTHESIS_MODEL = "mistral:7b"

# Temperature for all extraction calls.
# Low temperature = factual extraction, not creative generation. Do not raise this.
OLLAMA_TEMPERATURE = 0.1

# Max tokens for standard chunk calls (per-chunk prompts in Phase 3)
OLLAMA_NUM_PREDICT_DEFAULT = 4096

# Max tokens for assembly calls (Phase 3 final step per team).
# MUST be 8192 — the assembly writes full .md files including Replication Notes.
# 4096 truncates silently, losing the most valuable section. Do not lower this.
OLLAMA_NUM_PREDICT_ASSEMBLY = 8192

# Context window size. qwen2.5-coder:14b supports 32K. Keep headroom for prompts.
OLLAMA_NUM_CTX = 32768

# Repeat penalty — prevents output loops that corrupt .md files silently.
OLLAMA_REPEAT_PENALTY = 1.1

# Max retries for a failed Ollama call before marking the team as failed.
OLLAMA_MAX_RETRIES = 3

# -----------------------------------------------------------------------------
# File Walker
# -----------------------------------------------------------------------------

# Max characters of code per Ollama call.
# 60K chars ≈ 15K tokens — leaves headroom in a 32K context window for the prompt.
MAX_CHUNK_CHARS = 60_000

# Files larger than this get line-chunked (not skipped).
MAX_FILE_CHARS = 80_000

# Per-team chunk cap. Bounds worst-case time to ~7 min/team (20 chunks × ~20s/call).
# Without this, a single large monorepo could stall the pipeline for 2+ hours.
MAX_CHUNKS_PER_TEAM = 20

# Set True to skip test files and speed up the run at the cost of completeness.
SKIP_TEST_FILES = False

# Set True to delete repos/ after reviewing each team (saves disk space).
# Set False if you want to re-inspect repos manually after the run.
DELETE_REPOS_AFTER_REVIEW = False

# Directories to skip entirely during file walking (build artifacts, dependencies).
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".gradle", ".idea", ".vscode",
    "coverage", ".nyc_output", "vendor",
}

# File extensions to include in the review (code + config + docs).
INCLUDE_EXTENSIONS = {
    # Code
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb",
    ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt", ".scala",
    # Config / infra
    ".json", ".yaml", ".yml", ".toml", ".env", ".xml", ".tf",
    # Docs (for README pre-read)
    ".md", ".txt", ".rst",
    # Gosu (Guidewire-specific)
    ".gsx", ".grs", ".pcf", ".eti",
}

# File walker priority order for chunking (builds context progressively).
# config → readme → data_model → entrypoint → core_logic → api → frontend → infra → tests
FILE_CATEGORY_PRIORITY = [
    "config", "readme", "data_model", "entrypoint",
    "core_logic", "api", "frontend", "infra", "tests",
]

# Max lines in the file tree sent to the assembly prompt.
FILE_TREE_MAX_LINES = 150

# -----------------------------------------------------------------------------
# Repo Scoring
# -----------------------------------------------------------------------------

# Minimum score to be treated as HIGH confidence (clone + review without flagging).
HIGH_CONFIDENCE_THRESHOLD = 5

# Minimum score to be treated as LOW confidence (clone + review, flagged in low_confidence.txt).
# Anything below this with results: take top result, mark LOW_CONFIDENCE.
# Anything with zero results: mark NOT_FOUND.
LOW_CONFIDENCE_THRESHOLD = 2

# Max repo size in KB before switching to sparse checkout.
# 500_000 KB = ~500 MB. Repos above this are checked out with --no-checkout + sparse-checkout.
MAX_REPO_SIZE_KB = 500_000

# -----------------------------------------------------------------------------
# Parallelism
# NOTE (v1.3): These are intentionally two separate constants.
# DO NOT set REVIEW_PARALLEL_WORKERS > 1. Ollama queues requests on the GPU —
# parallelising Ollama calls causes queue contention, possible crashes, zero speedup.
# Cloning is I/O bound and safe to parallelise.
# -----------------------------------------------------------------------------

CLONE_PARALLEL_WORKERS = 10   # used by 02_clone_repos.py — safe, git I/O bound
REVIEW_PARALLEL_WORKERS = 1   # used by 03_review_repos.py — always 1, do not change

# -----------------------------------------------------------------------------
# Paths (relative to project root — run all scripts from project root)
# -----------------------------------------------------------------------------

TEAMS_FILE          = "teams.txt"
NAME_MAP_FILE       = "team_name_map.json"
MANIFEST_FILE       = "repos_manifest.json"
NOT_FOUND_FILE      = "not_found.txt"
LOW_CONFIDENCE_FILE = "low_confidence.txt"
REPOS_DIR           = "repos"
REVIEWS_DIR         = "reviews"
KNOWLEDGE_DIR       = "knowledge"
LOGS_DIR            = "logs"

# Knowledge output files (Phase 4)
MASTER_PATTERNS_FILE = "knowledge/MASTER_PATTERNS.md"
GAPS_FILE            = "knowledge/GAPS.md"
FEATURE_PLAN_FILE    = "knowledge/YOUR_FEATURE_PLAN.md"

# -----------------------------------------------------------------------------
# Leaderboard Scraping (Phase 0 — optional)
# Set this if the leaderboard is publicly accessible without auth.
# Leave as None to skip and use manual teams.txt instead.
# -----------------------------------------------------------------------------

LEADERBOARD_URL = None  # e.g. "https://devtrails.guidewire.com/leaderboard"

# -----------------------------------------------------------------------------
# Synthesis — Gap Analysis
# -----------------------------------------------------------------------------

# Technologies/patterns used by more than this fraction of teams are "table stakes".
# Items below this threshold are "gaps" (differentiation opportunities).
GAP_FREQUENCY_THRESHOLD = 0.15  # 15% of teams

# Guidewire-specific keywords to track across all Guidewire Integration sections.
GUIDEWIRE_KEYWORDS = [
    "ClaimCenter", "PolicyCenter", "BillingCenter", "ContactManager",
    "InsuranceSuite", "Cloud API", "Integration Framework", "Gosu",
    "OOTB", "PCF", "Guidewire Cloud", "Data Platform", "Jutro",
    "AppExchange", "Predictive Analytics", "Cyence",
]
