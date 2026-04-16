# src/03_review_repos.py
# Phase 3 — Deep Code Review Engine
#
# BUG 3 FIX: Missing clone dir was silently marked 'complete'. Separated NOT_FOUND check
#   from missing clone check. Missing clone is now marked 'failed', not 'complete'.
# BUG 4 FIX: --validate-only argument was missing from argparse, causing immediate crash.
# BUG 6 FIX: --rerun-section "Guidewire Integration" failed because code required "## Guidewire
#   Integration". Now normalizes the input by prepending "## " if not already present.
# BUG 7 FIX: Resume path skipped already-reviewed teams without updating review_status to
#   'complete' in the manifest, causing permanent false 'pending' counts.
#
# Usage:
#   python src/03_review_repos.py
#   python src/03_review_repos.py --rerun-section "Guidewire Integration"
#   python src/03_review_repos.py --validate-only

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (
    CODE_REVIEW_MODEL,
    DELETE_REPOS_AFTER_REVIEW,
    MAX_CHUNK_CHARS,
    MAX_CHUNKS_PER_TEAM,
    MAX_FILE_CHARS,
    REVIEW_PARALLEL_WORKERS,
)
from utils.chunker import chunk_files
from utils.file_walker import generate_file_tree, walk_and_classify
from utils.ollama_client import (
    check_ollama_available,
    ollama_assembly_call,
    ollama_generate_with_retry,
    unload_model,
)
from utils.validator import (
    REQUIRED_SECTIONS,
    extract_section,
    is_marked_failed,
    mark_failed,
    missing_sections,
    patch_review,
    validate_review,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

MANIFEST_PATH = Path('repos_manifest.json')
REVIEWS_DIR = Path('reviews')

assert REVIEW_PARALLEL_WORKERS == 1, (
    "REVIEW_PARALLEL_WORKERS must be 1. Ollama queues GPU calls — "
    "parallelism here adds contention with no speedup (Section 11.2)."
)


# =========================================================================== #
# Prompt builders                                                              #
# =========================================================================== #

def build_chunk_prompt(
    team_name: str,
    category: str,
    chunk_num: int,
    total_chunks: int,
    prior_context: str,
    file_contents: str,
) -> str:
    prior_block = (
        f"PRIOR ANALYSIS CONTEXT (from earlier chunks of the same repo):\n"
        f"{prior_context}\n\nNow analyse this new chunk:\n"
        if prior_context.strip() else ""
    )
    return f"""You are a precise technical code analyst. Your job is to extract what is EXPLICITLY present \
in the code. Do NOT infer, guess, or add context not visible in the code.
For any section where you find nothing: write exactly "NOT FOUND".
If code comments or documentation are in a non-English language, note the language \
and still extract the technical structure.

TEAM: {team_name}
CHUNK TYPE: {category} files — chunk {chunk_num} of {total_chunks}

{prior_block}
=== CODE ===
{file_contents}
=== END CODE ===

Answer ALL sections below. Be specific — use actual names, not generic descriptions.

TECH_STACK:
List every framework, library, language, and tool you can see imported, configured, \
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
Any Guidewire API endpoints, ClaimCenter/PolicyCenter/BillingCenter references, \
Guidewire data models, or Guidewire-specific patterns. VERY IMPORTANT.

UNUSUAL_PATTERNS:
Anything architecturally interesting, clever, or uncommon. If nothing: write NONE.

COMPLETENESS:
How complete does this section of code appear? Low / Medium / High. One sentence explaining why."""


def build_assembly_prompt(
    team_name: str,
    repo_url: str,
    confidence: str,
    file_tree: str,
    all_summaries: str,
) -> str:
    today = date.today().isoformat()
    return f"""You are writing a technical intelligence report for a hackathon analysis system.
Below are analysis summaries of different code sections from one team's repository.
Your job: synthesise them into one structured report.

RULES:
- Only include information that appears in the summaries below
- Do NOT add, infer, or guess anything
- Use the EXACT section headers shown in the output format
- If a section has no information from the summaries, write: NOT FOUND

TEAM: {team_name}
REPO URL: {repo_url}
CONFIDENCE: {confidence}

FILE TREE (for structural context):
{file_tree}

SUMMARIES FROM ALL CHUNKS:
{all_summaries}

Write the report in EXACTLY this format with EXACTLY these headers:

# {team_name}

**Repo:** {repo_url}
**Confidence:** {confidence}
**Review Date:** {today}

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
[This section should be detailed enough to actually rebuild the project]"""


def build_section_retry_prompt(
    team_name: str,
    repo_url: str,
    sections_needed: list[str],
    all_summaries: str,
) -> str:
    headers = '\n'.join(sections_needed)
    return f"""You are completing a partial technical intelligence report.
The following sections are MISSING or contain only "NOT FOUND".
Fill them in using ONLY the chunk summaries provided.
Do NOT add information not present in the summaries.

TEAM: {team_name}
REPO URL: {repo_url}

CHUNK SUMMARIES:
{all_summaries}

Write ONLY the sections listed below, using their exact headers:

{headers}

For each section, if you genuinely cannot find relevant information in the summaries, \
write: NOT FOUND"""


# =========================================================================== #
# Manifest helpers                                                             #
# =========================================================================== #

def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))


def save_manifest(manifest: list[dict]) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def update_manifest_status(manifest: list[dict], team_name: str, status: str) -> None:
    for entry in manifest:
        if entry['team_name'] == team_name:
            entry['review_status'] = status
            break
    save_manifest(manifest)


def write_empty_review(review_path: Path, team_name: str, repo_url: str, reason: str) -> None:
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        f"# {team_name}\n\n"
        f"**Repo:** {repo_url}\n"
        f"**Status:** {reason}\n\n"
        + '\n\n'.join(f"{s}\nNOT FOUND" for s in REQUIRED_SECTIONS),
        encoding='utf-8',
    )
    logger.info("[%s] Wrote stub review: %s", team_name, reason)


# =========================================================================== #
# Core per-team review                                                         #
# =========================================================================== #

def review_team(team_entry: dict, manifest: list[dict]) -> None:
    team_name = team_entry['team_name']
    safe_name  = team_entry['safe_name']
    repo_url   = team_entry.get('repo_url', 'UNKNOWN')
    confidence = team_entry.get('confidence', 'UNKNOWN')
    clone_path = Path('repos') / safe_name
    review_path = REVIEWS_DIR / f"{safe_name}.md"

    # ---- Step 1: Resumability -----------------------------------------------
    # BUG 7 FIX: original skipped without healing manifest status to 'complete',
    # leaving teams permanently stuck as 'pending' after a resumed run.
    if review_path.exists() and not is_marked_failed(review_path):
        if team_entry.get('review_status') != 'complete':
            update_manifest_status(manifest, team_name, 'complete')  # heal the manifest
        logger.info("[SKIP] %s — already reviewed", team_name)
        return

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Step 2: Handle NOT_FOUND and missing clone -------------------------
    # BUG 3 FIX: original combined these two checks, marking missing clones as
    # 'complete'. Separated so clone failures are correctly marked 'failed'.
    if team_entry.get('confidence') == 'NOT_FOUND':
        write_empty_review(review_path, team_name, repo_url, "REPO NOT FOUND")
        update_manifest_status(manifest, team_name, 'complete')
        return

    if not clone_path.exists():
        write_empty_review(review_path, team_name, repo_url, "CLONE MISSING — re-run Phase 2")
        mark_failed(review_path, "clone path missing for non-NOT_FOUND repo")
        update_manifest_status(manifest, team_name, 'failed')
        return

    # ---- Step 3: Walk and classify ------------------------------------------
    classified = walk_and_classify(clone_path)
    if not classified:
        write_empty_review(review_path, team_name, repo_url, "EMPTY REPO — no code files")
        update_manifest_status(manifest, team_name, 'complete')
        return

    # ---- Step 4: Chunk -------------------------------------------------------
    chunks = chunk_files(
        classified,
        max_chunk_chars=MAX_CHUNK_CHARS,
        max_file_chars=MAX_FILE_CHARS,
        max_chunks_per_team=MAX_CHUNKS_PER_TEAM,
    )

    if not chunks:
        write_empty_review(review_path, team_name, repo_url, "EMPTY REPO — chunker returned nothing")
        update_manifest_status(manifest, team_name, 'complete')
        return

    # ---- Step 5: Per-chunk calls with context chaining ----------------------
    chunk_summaries: list[str] = []
    accumulated_context = ""

    for chunk in chunks:
        chunk_num    = chunk['chunk_num']
        total_chunks = chunk['total_chunks']
        category     = chunk['label']
        file_content = chunk['content']

        prompt = build_chunk_prompt(
            team_name, category, chunk_num, total_chunks,
            accumulated_context, file_content,
        )

        summary = ollama_generate_with_retry(prompt, CODE_REVIEW_MODEL)

        if summary:
            chunk_summaries.append(summary)
            accumulated_context += f"\n---\nCHUNK {chunk_num} ({category}):\n{summary}"
        else:
            placeholder = f"CHUNK {chunk_num} ({category}): FAILED TO PROCESS"
            chunk_summaries.append(placeholder)
            logger.warning("[%s] Chunk %d/%d failed", team_name, chunk_num, total_chunks)

        print(f"  [{team_name}] Chunk {chunk_num}/{total_chunks} ({category}) done")

    # ---- Step 6: Assembly call (MUST use 8192 tokens) -----------------------
    file_tree    = generate_file_tree(clone_path)
    all_summaries = "\n\n---\n\n".join(chunk_summaries)
    assembly_prompt = build_assembly_prompt(
        team_name, repo_url, confidence, file_tree, all_summaries
    )

    md_content = ollama_assembly_call(assembly_prompt, CODE_REVIEW_MODEL)

    if not md_content:
        logger.error("[%s] Assembly call returned nothing — marking failed", team_name)
        write_empty_review(review_path, team_name, repo_url, "ASSEMBLY CALL FAILED")
        mark_failed(review_path, "assembly call returned nothing")
        update_manifest_status(manifest, team_name, 'failed')
        return

    # ---- Step 7: Write and validate -----------------------------------------
    review_path.write_text(md_content, encoding='utf-8')
    valid, reason = validate_review(review_path)

    if not valid:
        logger.warning("[%s] Validation failed: %s — attempting section retry", team_name, reason)
        gaps = missing_sections(review_path)
        if gaps:
            retry_prompt = build_section_retry_prompt(team_name, repo_url, gaps, all_summaries)
            retry_output = ollama_generate_with_retry(retry_prompt, CODE_REVIEW_MODEL)

            if retry_output:
                for section in gaps:
                    section_body = extract_section(retry_output, section)
                    if section_body:
                        patch_review(review_path, section, section_body)
                    else:
                        header_plain = section.lstrip('#').strip()
                        if header_plain in retry_output:
                            idx = retry_output.index(header_plain) + len(header_plain)
                            raw = retry_output[idx:].split('\n##')[0].strip()
                            if raw:
                                patch_review(review_path, section, raw)

                valid, reason = validate_review(review_path)

        if not valid:
            logger.error("[%s] Still invalid after retry: %s", team_name, reason)
            mark_failed(review_path, reason)
            update_manifest_status(manifest, team_name, 'failed')
            return

    if DELETE_REPOS_AFTER_REVIEW and clone_path.exists():
        shutil.rmtree(clone_path)
        logger.info("[%s] Deleted clone to free disk space", team_name)

    update_manifest_status(manifest, team_name, 'complete')
    print(f"  [{team_name}] Done ✓")


# =========================================================================== #
# Re-run mode                                                                  #
# =========================================================================== #

def rerun_section(section_header: str) -> None:
    """
    BUG 6 FIX: The documented CLI example used "Guidewire Integration" but the code
    required "## Guidewire Integration" (with ##). The mismatch caused an immediate
    "Unknown section" exit every time. Now normalizes input to accept both forms.
    """
    # Normalize: accept "Guidewire Integration" or "## Guidewire Integration"
    normalized = section_header if section_header.startswith("## ") else f"## {section_header}"

    if normalized not in REQUIRED_SECTIONS:
        print(f"Unknown section '{section_header}'. Valid sections:")
        for s in REQUIRED_SECTIONS:
            print(f"  {s.lstrip('# ')}")  # show without ## for readability
        sys.exit(1)

    section_header = normalized  # use the ## form from here on

    manifest = load_manifest()
    md_files = list(REVIEWS_DIR.glob('*.md'))
    print(f"Re-running section '{section_header}' across {len(md_files)} reviews...")

    for i, review_path in enumerate(md_files, 1):
        safe_name = review_path.stem
        entry = next((e for e in manifest if e['safe_name'] == safe_name), None)
        if not entry:
            logger.warning("No manifest entry for %s — skipping", safe_name)
            continue

        team_name = entry['team_name']
        repo_url  = entry.get('repo_url', 'UNKNOWN')
        content   = review_path.read_text(encoding='utf-8', errors='replace')

        body = extract_section(content, section_header)
        if body and not body.strip().upper().startswith('NOT FOUND'):
            logger.info("[%d/%d] %s — section already populated, skipping", i, len(md_files), team_name)
            continue

        print(f"[{i}/{len(md_files)}] {team_name} — refreshing '{section_header}'")

        existing_context = '\n\n'.join(
            f"{s}\n{extract_section(content, s)}"
            for s in REQUIRED_SECTIONS
            if s != section_header and s in content
        )

        retry_prompt = build_section_retry_prompt(
            team_name, repo_url, [section_header], existing_context
        )
        result = ollama_generate_with_retry(retry_prompt, CODE_REVIEW_MODEL)

        if result:
            new_body = extract_section(result, section_header) or result.strip()
            patch_review(review_path, section_header, new_body)
            print(f"  ✓ Patched")
        else:
            logger.warning("  Model returned nothing for %s", team_name)


# =========================================================================== #
# Main loop                                                                    #
# =========================================================================== #

def main() -> None:
    if not check_ollama_available(CODE_REVIEW_MODEL):
        print(f"ERROR: Ollama is not running or model '{CODE_REVIEW_MODEL}' is not pulled.")
        print(f"  Run: ollama pull {CODE_REVIEW_MODEL}")
        sys.exit(1)

    manifest = load_manifest()

    ordered = (
        [t for t in manifest if t.get('confidence') == 'HIGH'] +
        [t for t in manifest if t.get('confidence') == 'LOW']
    )

    not_found_count = sum(1 for t in manifest if t.get('confidence') == 'NOT_FOUND')
    total = len(ordered)
    print(f"\nStarting Phase 3 — {total} teams to review (skipping {not_found_count} NOT_FOUND teams)")
    print(f"Model: {CODE_REVIEW_MODEL}  |  Max chunks/team: {MAX_CHUNKS_PER_TEAM}")
    print(f"Estimated time: ~{total * 6 * 20 // 3600}–{total * 8 * 20 // 3600} hours\n")

    start = time.time()
    completed = 0
    failed    = 0

    for i, team_entry in enumerate(ordered, 1):
        team_name = team_entry['team_name']
        print(f"\n[{i}/{total}] {team_name}")

        try:
            review_team(team_entry, manifest)
            # Re-read status from manifest (review_team updates it in-place)
            updated = next((t for t in manifest if t['team_name'] == team_name), {})
            status = updated.get('review_status', '')
            if status == 'complete':
                completed += 1
            elif status == 'failed':
                failed += 1
        except KeyboardInterrupt:
            print("\n\nInterrupted — progress saved to repos_manifest.json. Resume anytime.")
            sys.exit(0)
        except Exception as exc:
            logger.error("[%s] Unexpected error: %s", team_name, exc, exc_info=True)
            update_manifest_status(manifest, team_name, 'failed')
            failed += 1
            continue

        if i % 10 == 0:
            elapsed = time.time() - start
            rate    = elapsed / i
            eta_s   = rate * (total - i)
            print(f"\n  ── Progress: {i}/{total} | "
                  f"done={completed} failed={failed} | "
                  f"ETA ~{eta_s/3600:.1f}h ──\n")

    print(f"\nUnloading {CODE_REVIEW_MODEL} from VRAM before Phase 4...")
    unload_model(CODE_REVIEW_MODEL)

    elapsed_total = time.time() - start
    print(f"\n{'='*50}")
    print(f"Phase 3 complete in {elapsed_total/3600:.1f}h")
    print(f"  Completed: {completed}  |  Failed: {failed}  |  Total: {total}")
    print(f"  Reviews written to: {REVIEWS_DIR}/")
    print(f"{'='*50}")


# =========================================================================== #
# Entry point                                                                  #
# =========================================================================== #

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Phase 3 — Deep Code Review Engine')

    parser.add_argument(
        '--rerun-section',
        metavar='SECTION',
        help='Re-run a single section across all existing reviews. '
             'E.g.: --rerun-section "Guidewire Integration"',
    )
    # BUG 4 FIX: --validate-only was passed by run_all.py but never defined here,
    # causing argparse to exit with an error before anything ran.
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Validate all existing review files and exit with 0 (pass) or 1 (fail)',
    )

    args = parser.parse_args()

    if args.validate_only:
        from utils.validator import validate_all
        summary = validate_all(REVIEWS_DIR)
        print(f"Passed: {summary['passed']} / Failed: {summary['failed']} / Rate: {summary['pass_rate']:.1%}")
        sys.exit(0 if summary['pass_rate'] >= 0.90 else 1)
    elif args.rerun_section:
        rerun_section(args.rerun_section)
    else:
        main()