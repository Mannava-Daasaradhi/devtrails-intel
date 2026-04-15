# utils/validator.py
# Validates .md review files after they are written by 03_review_repos.py.
# Also exposes extract_section() which is shared with 04_synthesize.py.
#
# Blueprint refs: Section 6.7 (validation logic), Section 7.1 (extract_section usage),
# Reviewer 3 bug fix — validate_review() must use extract_section(), not split().

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Required sections — every valid review must contain all of these.           #
# Order matches the assembly prompt output format (Section 6.6).              #
# --------------------------------------------------------------------------- #

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

# Marker written at the top of a .md when all retries are exhausted.
VALIDATION_FAILED_MARKER = "<!-- VALIDATION_FAILED -->\n"

# A section is "empty" if its content is only NOT FOUND (or blank).
_NOT_FOUND_RE = re.compile(r'^\s*not\s+found\s*$', re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Section extractor — used here AND by 04_synthesize.py                       #
# --------------------------------------------------------------------------- #

def extract_section(md_content: str, section_header: str) -> str:
    """
    Extract the text between `section_header` and the next ## heading (or EOF).

    Uses a regex so it handles arbitrary whitespace and trailing content cleanly.
    This is the canonical extraction function for the whole pipeline — every other
    module that needs section content should import this rather than calling split().

    BUG FIX (v1.3): The original validate_review() used content.split(section)[1]
    which returned everything after the first occurrence of the header, including all
    subsequent sections. If a header appeared more than once the result was wrong.
    This regex approach is correct regardless of header repetition.
    """
    pattern = rf'{re.escape(section_header)}\n(.*?)(?=\n## |\Z)'
    match = re.search(pattern, md_content, re.DOTALL)
    return match.group(1).strip() if match else ''


# --------------------------------------------------------------------------- #
# Core validator                                                               #
# --------------------------------------------------------------------------- #

def validate_review(filepath: str | Path) -> tuple[bool, str]:
    """
    Check that a review .md file is structurally complete and non-trivial.

    Two failure conditions:
      1. One or more required sections are missing entirely.
      2. Every present section contains only "NOT FOUND" — the model almost
         certainly failed to process the code.

    Returns
    -------
    (True, "OK") on success.
    (False, reason_string) on failure — reason is logged and returned to caller.

    The caller (03_review_repos.py) decides whether to retry or mark as failed.
    """
    content = Path(filepath).read_text(encoding='utf-8', errors='replace')

    # ---- 1. Check for VALIDATION_FAILED marker from a previous run ----------
    if content.startswith(VALIDATION_FAILED_MARKER):
        return False, "File was previously marked VALIDATION_FAILED"

    # ---- 2. Check all required sections are present -------------------------
    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    if missing:
        reason = f"Missing sections: {missing}"
        logger.warning("[validator] %s — %s", Path(filepath).name, reason)
        return False, reason

    # ---- 3. Check not every section is "NOT FOUND" --------------------------
    # Uses extract_section() — not split() — per the v1.3 bug fix.
    all_not_found = all(
        _NOT_FOUND_RE.match(extract_section(content, s))
        for s in REQUIRED_SECTIONS
        if s in content
    )
    if all_not_found:
        reason = "All sections are NOT FOUND — model likely failed to process this repo"
        logger.warning("[validator] %s — %s", Path(filepath).name, reason)
        return False, reason

    return True, "OK"


# --------------------------------------------------------------------------- #
# Identify which specific sections are missing or empty                       #
# --------------------------------------------------------------------------- #

def missing_sections(filepath: str | Path) -> list[str]:
    """
    Return a list of section headers that are either absent or contain only
    "NOT FOUND". Used by 03_review_repos.py to build a targeted retry prompt
    that asks the model to fill in only the gaps.
    """
    content = Path(filepath).read_text(encoding='utf-8', errors='replace')
    result = []
    for section in REQUIRED_SECTIONS:
        if section not in content:
            result.append(section)
            continue
        body = extract_section(content, section)
        if _NOT_FOUND_RE.match(body):
            result.append(section)
    return result


# --------------------------------------------------------------------------- #
# Patch helper — splice retry output into an existing .md file               #
# --------------------------------------------------------------------------- #

def patch_review(filepath: str | Path, section_header: str, new_content: str) -> None:
    """
    Replace the body of a single section in an existing .md file.

    Used by the re-review / retry flow in 03_review_repos.py:
      1. Detect which sections are missing/NOT FOUND via missing_sections().
      2. Send a targeted prompt to Ollama asking for only those sections.
      3. Call patch_review() for each section in the response.

    If the section doesn't exist yet it is appended at the end of the file.
    """
    path = Path(filepath)
    content = path.read_text(encoding='utf-8', errors='replace')

    pattern = rf'({re.escape(section_header)}\n)(.*?)(?=\n## |\Z)'
    replacement = rf'\g<1>{new_content.strip()}\n'

    if section_header in content:
        updated = re.sub(pattern, replacement, content, flags=re.DOTALL)
    else:
        # Section absent — append it
        updated = content.rstrip() + f"\n\n{section_header}\n{new_content.strip()}\n"

    path.write_text(updated, encoding='utf-8')
    logger.info("[validator] Patched section '%s' in %s", section_header, path.name)


# --------------------------------------------------------------------------- #
# Failure marker helpers                                                      #
# --------------------------------------------------------------------------- #

def mark_failed(filepath: str | Path, reason: str) -> None:
    """
    Prepend VALIDATION_FAILED_MARKER to a .md file so it is easily findable
    after a full run. Called when all retries are exhausted.

    The dashboard (05_dashboard.py) and synthesizer (04_synthesize.py) both
    skip files that begin with this marker.
    """
    path = Path(filepath)
    existing = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ""

    if not existing.startswith(VALIDATION_FAILED_MARKER):
        path.write_text(
            f"{VALIDATION_FAILED_MARKER}<!-- Reason: {reason} -->\n\n{existing}",
            encoding='utf-8',
        )
        logger.warning("[validator] Marked %s as VALIDATION_FAILED: %s", path.name, reason)


def is_marked_failed(filepath: str | Path) -> bool:
    """Quick check without reading the whole file."""
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            first_line = f.readline()
        return first_line.startswith(VALIDATION_FAILED_MARKER.strip())
    except FileNotFoundError:
        return False


# --------------------------------------------------------------------------- #
# Batch validation — used by 05_dashboard.py and quality gate checks          #
# --------------------------------------------------------------------------- #

def validate_all(reviews_dir: str | Path = 'reviews') -> dict:
    """
    Run validate_review() across every .md in reviews_dir.

    Returns a summary dict:
    {
        'total': int,
        'passed': int,
        'failed': int,
        'failed_files': [(filename, reason), ...],
        'pass_rate': float,   # 0.0 – 1.0
    }

    The quality gate (Section 13) requires pass_rate > 0.90.
    """
    reviews_path = Path(reviews_dir)
    files = list(reviews_path.glob('*.md'))

    passed, failed_files = 0, []
    for f in files:
        ok, reason = validate_review(f)
        if ok:
            passed += 1
        else:
            failed_files.append((f.name, reason))

    total = len(files)
    return {
        'total': total,
        'passed': passed,
        'failed': total - passed,
        'failed_files': failed_files,
        'pass_rate': passed / total if total else 0.0,
    }
