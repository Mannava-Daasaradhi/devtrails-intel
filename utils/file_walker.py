# =============================================================================
# utils/file_walker.py — DEVTrails 2026 Competitive Intelligence Pipeline
# Walks a cloned repo, classifies every file into a category, and generates
# the file tree for the assembly prompt.
#
# Consumed by: src/03_review_repos.py (via chunker.py)
# =============================================================================

import sys
from pathlib import Path
from typing import Optional

# Project root on sys.path so we can import config.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    SKIP_DIRS,
    INCLUDE_EXTENSIONS,
    SKIP_TEST_FILES,
    MAX_FILE_CHARS,
    FILE_CATEGORY_PRIORITY,
    FILE_TREE_MAX_LINES,
)

# =============================================================================
# Skip predicates
# =============================================================================

# Extensions to never read at all (binaries, lock files, minified assets).
_SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".tiff",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".jar", ".war", ".ear", ".class",
    ".lock", ".sum",                    # dependency lock files — no signal
    ".map",                             # source maps — minified JS source
    ".snap",                            # jest snapshots — rarely useful
    ".pyc", ".pyo",                     # compiled Python
    ".so", ".dll", ".dylib", ".exe",    # native binaries
    ".woff", ".woff2", ".ttf", ".eot",  # fonts
    ".mp3", ".mp4", ".avi", ".mov",     # media
    ".db", ".sqlite", ".sqlite3",       # binary databases
}

# Filenames to always skip regardless of extension.
_SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "Gemfile.lock",
    "composer.lock",
    ".DS_Store",
    "Thumbs.db",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".eslintignore",
    ".prettierignore",
    "CHANGELOG.md",
    "LICENCE",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
}

# Name patterns for test files (used when SKIP_TEST_FILES=True).
_TEST_INDICATORS = {"test", "spec", "__tests__", "testing", "fixture", "fixtures", "mock", "mocks"}


def _is_test_file(path: Path) -> bool:
    """Return True if any part of the path looks like a test file or folder."""
    parts_lower = [p.lower() for p in path.parts]
    stem_lower = path.stem.lower()
    return (
        any(indicator in parts_lower for indicator in _TEST_INDICATORS)
        or stem_lower.startswith("test_")
        or stem_lower.endswith("_test")
        or stem_lower.endswith(".spec")
        or stem_lower.endswith(".test")
    )


def _should_skip(path: Path, root: Path) -> bool:
    """
    Return True if this file should be excluded entirely from the walk.
    Checks skip dirs, skip extensions, skip filenames, and optionally test files.
    """
    # Check every component of the relative path against SKIP_DIRS
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True  # path not under root — shouldn't happen, skip to be safe

    for part in rel.parts[:-1]:  # all directory components, not the filename itself
        if part in SKIP_DIRS or part.startswith("."):
            return True

    # Extension / filename checks
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return True
    if path.name in _SKIP_FILENAMES:
        return True
    # Only include extensions we care about
    if path.suffix.lower() not in INCLUDE_EXTENSIONS:
        return True

    # Skip minified files by naming convention (.min.js, .min.css)
    if path.name.endswith(".min.js") or path.name.endswith(".min.css"):
        return True

    if SKIP_TEST_FILES and _is_test_file(path):
        return True

    return False


# =============================================================================
# File classification
# =============================================================================

# Category classifiers — ordered list of (category_name, list_of_predicates).
# First matching category wins. Files that match nothing go to "core_logic".
#
# Each predicate is a callable(Path) -> bool. We use lambdas rather than
# a big if/elif chain so new rules can be inserted at any position easily.

_CONFIG_FILENAMES = {
    "package.json", "requirements.txt", "requirements.in",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", ".env.template",
    "pyproject.toml", "setup.py", "setup.cfg",
    "application.yml", "application.yaml", "application.properties",
    "config.yaml", "config.yml", "config.json",
    "tsconfig.json", "tsconfig.base.json",
    "webpack.config.js", "webpack.config.ts",
    "vite.config.js", "vite.config.ts",
    "next.config.js", "next.config.ts",
    "jest.config.js", "jest.config.ts",
    ".babelrc", "babel.config.js",
    "settings.py", "settings.yml",  # common Django/general config
    "Makefile", "makefile",
}

_ENTRYPOINT_FILENAMES = {
    "main.py", "app.py", "server.py", "run.py", "wsgi.py", "asgi.py",
    "index.js", "index.ts",
    "app.js", "app.ts",
    "server.js", "server.ts",
    "main.go",
    "Main.java", "Application.java",
    "Program.cs",
    "main.rs",
    "index.php", "app.php",
    "application.py",
    "__main__.py",
    "manage.py",  # Django entry point
}

_DATA_MODEL_KEYWORDS_IN_NAME = {
    "model", "schema", "entity", "migration", "migrate",
    "orm", "database", "db", "dao", "repository",
}

_DATA_MODEL_KEYWORDS_IN_PATH = {
    "/models/", "/schemas/", "/entities/", "/db/",
    "/migrations/", "/database/", "/repositories/",
}

_API_KEYWORDS_IN_PATH = {
    "/api/", "/routes/", "/controllers/", "/handlers/",
    "/endpoints/", "/resources/", "/views/", "/rest/",
    "/grpc/", "/graphql/",
}

_CORE_KEYWORDS_IN_PATH = {
    "/src/", "/lib/", "/core/", "/services/", "/backend/",
    "/business/", "/domain/", "/logic/", "/utils/", "/helpers/",
    "/internal/", "/pkg/",
}

_FRONTEND_KEYWORDS_IN_PATH = {
    "/frontend/", "/ui/", "/client/", "/pages/", "/components/",
    "/web/", "/static/", "/public/assets/", "/app/components/",
    "/app/pages/",
}

_INFRA_KEYWORDS_IN_PATH = {
    "/infra/", "/k8s/", "/kubernetes/", "/terraform/", "/deploy/",
    "/helm/", "/ansible/", "/ci/", "/.github/", "/scripts/",
    "/ops/", "/devops/",
}

_TEST_KEYWORDS_IN_PATH = {
    "/test/", "/tests/", "/spec/", "/__tests__/", "/testing/",
    "/fixtures/", "/mocks/",
}


def _path_contains(path: Path, keywords: set) -> bool:
    """Return True if the forward-slash-normalised path string contains any keyword."""
    path_str = "/" + path.as_posix() + "/"
    return any(kw in path_str for kw in keywords)


_CLASSIFIERS: list[tuple[str, list]] = [
    ("config", [
        lambda f: f.name in _CONFIG_FILENAMES,
        lambda f: f.suffix in {".env"} and f.name != ".env",  # .env.example etc
        lambda f: f.name.endswith(".properties") and "application" in f.name.lower(),
    ]),
    ("readme", [
        lambda f: f.name.lower().startswith("readme"),
    ]),
    ("data_model", [
        lambda f: any(kw in f.stem.lower() for kw in _DATA_MODEL_KEYWORDS_IN_NAME),
        lambda f: _path_contains(f, _DATA_MODEL_KEYWORDS_IN_PATH),
    ]),
    ("entrypoint", [
        lambda f: f.name in _ENTRYPOINT_FILENAMES,
    ]),
    ("api", [
        lambda f: _path_contains(f, _API_KEYWORDS_IN_PATH),
    ]),
    ("core_logic", [
        lambda f: _path_contains(f, _CORE_KEYWORDS_IN_PATH),
    ]),
    ("frontend", [
        lambda f: _path_contains(f, _FRONTEND_KEYWORDS_IN_PATH),
        lambda f: f.suffix.lower() in {".jsx", ".tsx", ".vue", ".svelte"},
    ]),
    ("infra", [
        lambda f: _path_contains(f, _INFRA_KEYWORDS_IN_PATH),
        lambda f: f.suffix.lower() in {".tf", ".tfvars"},
    ]),
    ("tests", [
        lambda f: _path_contains(f, _TEST_KEYWORDS_IN_PATH),
        lambda f: _is_test_file(f),
    ]),
]


def classify_file(path: Path) -> str:
    """
    Return the category name for a single file path.
    Tries each classifier in order — first match wins.
    Falls back to "core_logic" if nothing matches.
    """
    for category, predicates in _CLASSIFIERS:
        for predicate in predicates:
            try:
                if predicate(path):
                    return category
            except Exception:
                continue  # malformed path — skip predicate
    return "core_logic"  # catch-all


# =============================================================================
# File reading
# =============================================================================

def read_file_safe(path: Path) -> Optional[str]:
    """
    Read a file, trying UTF-8 first then Latin-1 as a fallback.
    Returns None if the file can't be read (binary, permission error, etc.).
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=encoding, errors="replace")
            # Heuristic: if more than 20% of characters are replacement chars,
            # treat as binary and skip.
            replacement_ratio = text.count("\ufffd") / max(len(text), 1)
            if replacement_ratio > 0.20:
                return None
            return text
        except (OSError, PermissionError):
            return None
        except Exception:
            continue
    return None


def _split_file_by_lines(content: str, max_chars: int, filepath: Path) -> list[tuple[str, str]]:
    """
    Split a large file's content into chunks of at most max_chars characters,
    splitting on line boundaries. Returns [(label, chunk_content), ...].
    """
    lines = content.splitlines(keepends=True)
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > max_chars and current:
            chunk_text = "".join(current)
            chunks.append(chunk_text)
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        chunks.append("".join(current))

    total = len(chunks)
    return [
        (f"{filepath} [part {i + 1}/{total}]", chunk)
        for i, chunk in enumerate(chunks)
    ]


# =============================================================================
# Main walk function
# =============================================================================

def walk_and_classify(
    clone_path: Path,
) -> dict[str, list[tuple[str, str]]]:
    """
    Walk a cloned repository and return a dict mapping category name to a list
    of (label, content) tuples ready for chunking.

    label is typically the relative file path string (e.g. "src/models/user.py"),
    but may be suffixed with " [part N/M]" for large files that were line-split.

    Returns an empty dict if the repo has no readable files.

    Flat-repo fallback (from blueprint Section 6.2):
    If fewer than 3 files were classified into named categories (config, readme,
    data_model, entrypoint, api, frontend, infra, tests — excluding core_logic),
    ALL files are reclassified as core_logic. This handles repos that don't follow
    any standard directory conventions.
    """
    if not clone_path.exists() or not clone_path.is_dir():
        return {}

    # category → list of (label, content)
    classified: dict[str, list[tuple[str, str]]] = {cat: [] for cat in FILE_CATEGORY_PRIORITY}
    classified["core_logic"] = classified.get("core_logic", [])

    for file_path in sorted(clone_path.rglob("*")):
        if not file_path.is_file():
            continue
        if _should_skip(file_path, clone_path):
            continue

        content = read_file_safe(file_path)
        if content is None or not content.strip():
            continue

        # Use a clean relative label for the prompt
        try:
            label = str(file_path.relative_to(clone_path))
        except ValueError:
            label = str(file_path)

        category = classify_file(file_path)

        if len(content) > MAX_FILE_CHARS:
            # Large file: split into labelled sub-chunks
            parts = _split_file_by_lines(content, MAX_FILE_CHARS, Path(label))
            classified.setdefault(category, []).extend(parts)
        else:
            classified.setdefault(category, []).append((label, content))

    # Remove empty categories
    classified = {k: v for k, v in classified.items() if v}

    if not classified:
        return {}

    # Flat-repo fallback: if fewer than 3 non-core_logic files exist, flatten all to core_logic
    non_core_count = sum(
        len(v) for k, v in classified.items() if k != "core_logic"
    )
    if non_core_count < 3:
        all_files: list[tuple[str, str]] = []
        for files in classified.values():
            all_files.extend(files)
        return {"core_logic": all_files}

    return classified


# =============================================================================
# File tree generator for the assembly prompt
# =============================================================================

def generate_file_tree(clone_path: Path, max_lines: int = FILE_TREE_MAX_LINES) -> str:
    """
    Generate a compact indented file tree of the cloned repo.
    Skips SKIP_DIRS and hidden directories.
    Caps output at max_lines lines to avoid bloating the assembly prompt.

    Returns a string ready to be inserted into {repo_file_tree} in the prompt.
    """
    if not clone_path.exists():
        return "(repo directory not found)"

    lines: list[str] = []

    for item in sorted(clone_path.rglob("*")):
        # Skip hidden and unwanted directories
        try:
            rel = item.relative_to(clone_path)
        except ValueError:
            continue

        # Skip if any parent directory is in SKIP_DIRS or starts with "."
        skip = False
        for part in rel.parts[:-1]:
            if part in SKIP_DIRS or part.startswith("."):
                skip = True
                break
        if skip:
            continue

        # Skip the item itself if it's a directory in SKIP_DIRS
        if item.is_dir() and (item.name in SKIP_DIRS or item.name.startswith(".")):
            continue

        depth = len(rel.parts) - 1
        indent = "  " * depth
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{indent}{item.name}{suffix}")

    if not lines:
        return "(empty repository)"

    if len(lines) > max_lines:
        shown = lines[:max_lines]
        shown.append(f"... ({len(lines) - max_lines} more items truncated)")
        return "\n".join(shown)

    return "\n".join(lines)


# =============================================================================
# Quick stats helper (used by 03_review_repos.py for logging)
# =============================================================================

def count_classified_files(classified: dict[str, list[tuple[str, str]]]) -> dict[str, int]:
    """Return a dict of category → file (or chunk) count for logging."""
    return {cat: len(files) for cat, files in classified.items()}


# =============================================================================
# CLI self-test — run directly to verify walker works on a local repo
# Usage: python utils/file_walker.py path/to/cloned/repo
# =============================================================================

if __name__ == "__main__":
    import json

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    print(f"Walking: {target.resolve()}\n")

    classified = walk_and_classify(target)

    if not classified:
        print("No files found (or all skipped).")
        sys.exit(0)

    total = sum(len(v) for v in classified.values())
    print(f"Total file/chunk entries: {total}")
    print(f"Categories found: {list(classified.keys())}\n")

    for cat in FILE_CATEGORY_PRIORITY:
        if cat in classified:
            print(f"  {cat}: {len(classified[cat])} entries")
            for label, content in classified[cat][:3]:
                print(f"    - {label} ({len(content):,} chars)")
            if len(classified[cat]) > 3:
                print(f"    ... and {len(classified[cat]) - 3} more")
    print()

    print("File tree (first 30 lines):")
    tree = generate_file_tree(target, max_lines=30)
    print(tree)
