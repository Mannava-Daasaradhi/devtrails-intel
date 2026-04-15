# utils/chunker.py
# Groups classified files into prompt-sized chunks for Ollama review.
# Follows the blueprint's grouping order (Section 6.3) and per-team chunk cap (Section 6.2).

import logging
from pathlib import Path
from typing import Iterator

# Grouping order matters — builds context progressively for the model.
# config and readme first so later chunks have architectural grounding.
CATEGORY_ORDER = [
    'config',
    'readme',
    'data_model',
    'entrypoint',
    'core_logic',
    'api',
    'frontend',
    'infra',
    'tests',
    'uncategorised',   # catch-all from file_walker flat-repo fallback
]

FILE_SEPARATOR = "=== FILE: {filepath} ===\n{content}\n"

logger = logging.getLogger(__name__)


def _read_file_safe(filepath: Path) -> str:
    """Read a file, returning empty string on any decode error."""
    try:
        return filepath.read_text(encoding='utf-8', errors='replace')
    except Exception as exc:
        logger.warning("Could not read %s: %s", filepath, exc)
        return ""


def _split_into_chunks(text: str, max_chars: int, label: str) -> list[tuple[str, str]]:
    """
    Split a single large text block into parts that each fit inside max_chars.
    Returns a list of (label_with_part_suffix, chunk_text).
    """
    if len(text) <= max_chars:
        return [(label, text)]

    parts = []
    raw_chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    total = len(raw_chunks)
    for idx, piece in enumerate(raw_chunks, start=1):
        part_label = f"{label} [part {idx}/{total}]"
        parts.append((part_label, piece))
    return parts


def chunk_files(
    classified_files: dict[str, list[Path]],
    max_chunk_chars: int = 60_000,
    max_file_chars: int = 80_000,
    max_chunks_per_team: int = 20,
) -> list[dict]:
    """
    Build a list of chunk dicts ready for the per-chunk Ollama prompt.

    Parameters
    ----------
    classified_files : dict mapping category name → list of Path objects
        Output of file_walker.walk_and_classify().
    max_chunk_chars : int
        Maximum total code characters per Ollama call (default 60 000).
        Leaves room for the prompt template around the code block.
    max_file_chars : int
        Files larger than this are split into parts before grouping (default 80 000).
    max_chunks_per_team : int
        Hard cap on total chunks produced. Excess chunks are dropped with a warning.
        Prevents a single huge repo from stalling the pipeline for hours (Section 6.2).

    Returns
    -------
    list of dicts, each with:
        {
            'chunk_num': int,          # 1-based index
            'total_chunks': int,       # filled in after all chunks are built
            'category': str,           # primary category label for this chunk
            'label': str,              # human-readable label, e.g. "core_logic [part 2/5]"
            'content': str,            # concatenated file blocks, ready for the prompt
        }
    """
    # ------------------------------------------------------------------ #
    # 1. Iterate categories in priority order, build candidate chunks.    #
    # ------------------------------------------------------------------ #
    raw_chunks: list[dict] = []   # accumulate before applying chunk cap

    for category in CATEGORY_ORDER:
        files = classified_files.get(category, [])
        if not files:
            continue

        # Accumulate file blocks into groups that fit within max_chunk_chars.
        current_block = ""
        current_files: list[str] = []

        for filepath in files:
            content = _read_file_safe(filepath)
            if not content.strip():
                continue  # skip empty / unreadable files silently

            # Large file: split into parts first, treat each part as its own file entry.
            if len(content) > max_file_chars:
                parts = _split_into_chunks(content, max_file_chars, str(filepath))
                file_entries = [
                    (f"{filepath} [part {i+1}/{len(parts)}]", chunk)
                    for i, (_, chunk) in enumerate(parts)
                ]
            else:
                file_entries = [(str(filepath), content)]

            for file_label, file_content in file_entries:
                block = FILE_SEPARATOR.format(filepath=file_label, content=file_content)

                if current_block and len(current_block) + len(block) > max_chunk_chars:
                    # Current group is full — flush it.
                    raw_chunks.append({
                        'category': category,
                        'label': category,
                        'content': current_block,
                    })
                    current_block = block
                    current_files = [file_label]
                else:
                    current_block += block
                    current_files.append(file_label)

        # Flush remaining content for this category.
        if current_block.strip():
            raw_chunks.append({
                'category': category,
                'label': category,
                'content': current_block,
            })

    # ------------------------------------------------------------------ #
    # 2. If a category produced multiple sequential chunks, label them    #
    #    "category [part X/N]" so the model knows where it is.           #
    # ------------------------------------------------------------------ #
    # Count how many chunks came from each category to build part labels.
    from collections import Counter
    category_counts = Counter(c['category'] for c in raw_chunks)
    category_seen: Counter = Counter()

    for chunk in raw_chunks:
        cat = chunk['category']
        total_for_cat = category_counts[cat]
        category_seen[cat] += 1
        if total_for_cat > 1:
            chunk['label'] = f"{cat} [part {category_seen[cat]}/{total_for_cat}]"
        else:
            chunk['label'] = cat

    # ------------------------------------------------------------------ #
    # 3. Apply per-team chunk cap (Section 6.2 / config MAX_CHUNKS_PER_TEAM). #
    # ------------------------------------------------------------------ #
    if len(raw_chunks) > max_chunks_per_team:
        logger.warning(
            "Repo produced %d chunks — capping at %d. "
            "Dropped categories: %s",
            len(raw_chunks),
            max_chunks_per_team,
            [c['label'] for c in raw_chunks[max_chunks_per_team:]],
        )
        raw_chunks = raw_chunks[:max_chunks_per_team]

    # ------------------------------------------------------------------ #
    # 4. Assign final chunk_num / total_chunks fields.                    #
    # ------------------------------------------------------------------ #
    total = len(raw_chunks)
    chunks: list[dict] = []
    for idx, chunk in enumerate(raw_chunks, start=1):
        chunks.append({
            'chunk_num': idx,
            'total_chunks': total,
            'category': chunk['category'],
            'label': chunk['label'],
            'content': chunk['content'],
        })

    logger.info("Built %d chunk(s) from %d categories.", total, len(classified_files))
    return chunks


# --------------------------------------------------------------------------- #
# Convenience iterator — yields one chunk at a time for memory efficiency.    #
# --------------------------------------------------------------------------- #
def iter_chunks(
    classified_files: dict[str, list[Path]],
    max_chunk_chars: int = 60_000,
    max_file_chars: int = 80_000,
    max_chunks_per_team: int = 20,
) -> Iterator[dict]:
    """Thin wrapper around chunk_files() that yields chunks one by one."""
    for chunk in chunk_files(
        classified_files,
        max_chunk_chars=max_chunk_chars,
        max_file_chars=max_file_chars,
        max_chunks_per_team=max_chunks_per_team,
    ):
        yield chunk
