# utils/validator.py
# Validates .md review files after they are written by 03_review_repos.py.
# Also exposes extract_section() which is shared with 04_synthesize.py.
#
# BUG 10 FIX: patch_review() used re.sub() with a string replacement containing \g<1>,
# which interprets backslashes in new_content as regex backreferences, corrupting files
# that contain Windows paths, \n, or similar sequences. Fixed with a lambda replacement.

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

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

VALIDATION_FAILED_MARKER = "<!-- VALIDATION_FAILED -->\n"

_NOT_FOUND_RE = re.compile(r'^\s*not\s+found\s*$', re.IGNORECASE)


def extract_section(md_content: str, section_header: str) -> str:
    pattern = rf'{re.escape(section_header)}\n(.*?)(?=\n## |\Z)'
    match = re.search(pattern, md_content, re.DOTALL)
    return match.group(1).strip() if match else ''


def validate_review(filepath: str | Path) -> tuple[bool, str]:
    content = Path(filepath).read_text(encoding='utf-8', errors='replace')

    if content.startswith(VALIDATION_FAILED_MARKER):
        return False, "File was previously marked VALIDATION_FAILED"

    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    if missing:
        reason = f"Missing sections: {missing}"
        logger.warning("[validator] %s — %s", Path(filepath).name, reason)
        return False, reason

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


def missing_sections(filepath: str | Path) -> list[str]:
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


def patch_review(filepath: str | Path, section_header: str, new_content: str) -> None:
    """
    Replace the body of a single section in an existing .md file.

    BUG 10 FIX: The original used rf'\\g<1>{new_content.strip()}\\n' as the replacement
    string in re.sub(). If new_content contains backslashes (Windows paths, \\n, \\1, etc.),
    re.sub() interprets them as regex backreferences and corrupts the file silently.
    Fixed by using a lambda which bypasses all backreference interpretation.
    """
    path = Path(filepath)
    content = path.read_text(encoding='utf-8', errors='replace')

    pattern = rf'({re.escape(section_header)}\n)(.*?)(?=\n## |\Z)'
    stripped = new_content.strip()

    if section_header in content:
        # Lambda replacement: no backreference interpretation of new_content
        updated = re.sub(
            pattern,
            lambda m: f"{m.group(1)}{stripped}\n",
            content,
            flags=re.DOTALL,
        )
    else:
        updated = content.rstrip() + f"\n\n{section_header}\n{stripped}\n"

    path.write_text(updated, encoding='utf-8')
    logger.info("[validator] Patched section '%s' in %s", section_header, path.name)


def mark_failed(filepath: str | Path, reason: str) -> None:
    path = Path(filepath)
    existing = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ""

    if not existing.startswith(VALIDATION_FAILED_MARKER):
        path.write_text(
            f"{VALIDATION_FAILED_MARKER}<!-- Reason: {reason} -->\n\n{existing}",
            encoding='utf-8',
        )
        logger.warning("[validator] Marked %s as VALIDATION_FAILED: %s", path.name, reason)


def is_marked_failed(filepath: str | Path) -> bool:
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            first_line = f.readline()
        return first_line.startswith(VALIDATION_FAILED_MARKER.strip())
    except FileNotFoundError:
        return False


def validate_all(reviews_dir: str | Path = 'reviews') -> dict:
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
