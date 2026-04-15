# utils/chunker.py
# Groups classified files into prompt-sized chunks for Ollama review.
# Follows the blueprint's grouping order (Section 6.3) and per-team chunk cap (Section 6.2).
#
# BUG 1 FIX: walk_and_classify() returns dict[str, list[tuple[str, str]]] (label, content pairs),
# but the original chunk_files() treated each item as a Path and called .read_text() on it.
# Fixed by checking isinstance(file_item, tuple) and handling both tuple and Path inputs.

import logging
from pathlib import Path
from typing import Iterator

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
    'uncategorised',
]

FILE_SEPARATOR = "=== FILE: {filepath} ===\n{content}\n"

logger = logging.getLogger(__name__)


def _read_file_safe(filepath: Path) -> str:
    try:
        return filepath.read_text(encoding='utf-8', errors='replace')
    except Exception as exc:
        logger.warning("Could not read %s: %s", filepath, exc)
        return ""


def _split_into_chunks(text: str, max_chars: int, label: str) -> list[tuple[str, str]]:
    if len(text) <= max_chars:
        return [(label, text)]
    parts = []
    raw_chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    total = len(raw_chunks)
    for idx, piece in enumerate(raw_chunks, start=1):
        parts.append((f"{label} [part {idx}/{total}]", piece))
    return parts


def chunk_files(
    classified_files: dict[str, list],
    max_chunk_chars: int = 60_000,
    max_file_chars: int = 80_000,
    max_chunks_per_team: int = 20,
) -> list[dict]:
    raw_chunks: list[dict] = []

    for category in CATEGORY_ORDER:
        files = classified_files.get(category, [])
        if not files:
            continue

        current_block = ""
        current_files: list[str] = []

        for file_item in files:
            # BUG 1 FIX: walk_and_classify returns (label, content) tuples.
            # Handle both tuple and Path/str inputs gracefully.
            if isinstance(file_item, tuple) and len(file_item) == 2:
                file_label, content = file_item
            else:
                file_label = str(file_item)
                content = _read_file_safe(Path(file_item))

            if not content.strip():
                continue

            if len(content) > max_file_chars:
                file_entries = _split_into_chunks(content, max_file_chars, file_label)
            else:
                file_entries = [(file_label, content)]

            for flabel, fcontent in file_entries:
                block = FILE_SEPARATOR.format(filepath=flabel, content=fcontent)

                if current_block and len(current_block) + len(block) > max_chunk_chars:
                    raw_chunks.append({
                        'category': category,
                        'label': category,
                        'content': current_block,
                    })
                    current_block = block
                    current_files = [flabel]
                else:
                    current_block += block
                    current_files.append(flabel)

        if current_block.strip():
            raw_chunks.append({
                'category': category,
                'label': category,
                'content': current_block,
            })

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

    if len(raw_chunks) > max_chunks_per_team:
        logger.warning(
            "Repo produced %d chunks — capping at %d. Dropped: %s",
            len(raw_chunks), max_chunks_per_team,
            [c['label'] for c in raw_chunks[max_chunks_per_team:]],
        )
        raw_chunks = raw_chunks[:max_chunks_per_team]

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


def iter_chunks(
    classified_files: dict[str, list],
    max_chunk_chars: int = 60_000,
    max_file_chars: int = 80_000,
    max_chunks_per_team: int = 20,
) -> Iterator[dict]:
    for chunk in chunk_files(
        classified_files,
        max_chunk_chars=max_chunk_chars,
        max_file_chars=max_file_chars,
        max_chunks_per_team=max_chunks_per_team,
    ):
        yield chunk
