# =============================================================================
# utils/name_sanitizer.py — DEVTrails 2026 Competitive Intelligence Pipeline
# Converts raw team names to filesystem-safe identifiers.
# Produces team_name_map.json consumed by every downstream script.
# =============================================================================

import re
import json
import sys
from pathlib import Path
from collections import defaultdict

# Characters illegal on Windows, Linux, or macOS file systems.
# Using a single superset so the map is cross-platform.
ILLEGAL_CHARS_RE = re.compile(r'[\\/*?:"<>|]')


def sanitize_name(name: str) -> str:
    """
    Convert a team name to a safe filesystem name.

    Rules applied in order:
    1. Replace illegal path characters with underscores.
    2. Collapse multiple whitespace runs to a single space.
    3. Strip leading/trailing whitespace.
    4. Cap at 100 characters (NTFS/ext4 safe; leaves room for _N suffix).

    The function is deterministic — same input always produces same output.
    Reversibility is handled via the map file, not this function.
    """
    safe = ILLEGAL_CHARS_RE.sub("_", name)      # step 1: illegal chars → _
    safe = re.sub(r"\s+", " ", safe).strip()     # step 2-3: normalise whitespace
    safe = safe[:100]                             # step 4: cap length
    return safe


def build_name_map(
    teams_file: str = "teams.txt",
    output: str = "team_name_map.json",
) -> dict:
    """
    Read teams.txt and produce team_name_map.json.

    Map format: { "Original Team Name": "safe_filesystem_name", ... }

    Collision handling (v1.3 bug-fix):
    If teams A, B, C all sanitize to the same safe name "X":
      A → "X"
      B → "X_1"
      C → "X_2"
    Uses a dedicated collision_counter dict — NOT list.count() — which had a
    bug where both B and C received "X_1" because the count of "X" (not "X_1")
    was still 1 when processing C.

    Returns the mapping dict (original → safe).
    Writes JSON to `output` path.
    Raises FileNotFoundError if teams_file does not exist.
    """
    teams_path = Path(teams_file)
    if not teams_path.exists():
        raise FileNotFoundError(
            f"teams.txt not found at '{teams_file}'.\n"
            "Create it first (Phase 0) — one team name per line, UTF-8 encoding."
        )

    raw_names = teams_path.read_text(encoding="utf-8").splitlines()

    # Drop blank lines with a clear warning (blank lines waste API calls downstream).
    blank_count = sum(1 for n in raw_names if not n.strip())
    if blank_count:
        print(
            f"WARNING: {blank_count} blank line(s) found in {teams_file} and skipped. "
            "Fix teams.txt — blank lines waste a GitHub API call each.",
            file=sys.stderr,
        )
    names = [n for n in raw_names if n.strip()]

    # Check for duplicates early — report but don't abort (let caller decide).
    seen: dict[str, int] = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    dupes = {n: c for n, c in seen.items() if c > 1}
    if dupes:
        print(
            f"WARNING: {len(dupes)} duplicate team name(s) found in {teams_file}:\n"
            + "\n".join(f"  '{n}' appears {c}x" for n, c in dupes.items())
            + "\nDuplicates will each get their own safe name via the collision counter.",
            file=sys.stderr,
        )

    mapping: dict[str, str] = {}           # original → safe
    assigned_safe_names: set[str] = set()  # safe names already in use
    collision_counter: defaultdict[str, int] = defaultdict(int)

    for name in names:
        base_safe = sanitize_name(name)
        safe = base_safe

        # Resolve collisions: if this safe name is taken, append _N.
        if safe in assigned_safe_names:
            collision_counter[base_safe] += 1
            safe = f"{base_safe}_{collision_counter[base_safe]}"
            # Extremely unlikely, but guard against the suffixed name also colliding.
            while safe in assigned_safe_names:
                collision_counter[base_safe] += 1
                safe = f"{base_safe}_{collision_counter[base_safe]}"

        mapping[name] = safe
        assigned_safe_names.add(safe)

    # Write the map.
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    collision_total = sum(collision_counter.values())
    print(
        f"Name map written to '{output}': {len(mapping)} entries"
        + (f", {collision_total} collision(s) resolved" if collision_total else "")
        + "."
    )
    return mapping


def load_name_map(path: str = "team_name_map.json") -> tuple[dict, dict]:
    """
    Load team_name_map.json and return both directions as a tuple:
      (original_to_safe, safe_to_original)

    Usage in downstream scripts:
        from utils.name_sanitizer import load_name_map
        NAME_MAP, SAFE_MAP = load_name_map()
        clone_path = Path("repos") / NAME_MAP[team_name]
        review_path = Path("reviews") / (NAME_MAP[team_name] + ".md")
    """
    map_path = Path(path)
    if not map_path.exists():
        raise FileNotFoundError(
            f"team_name_map.json not found at '{path}'.\n"
            "Run: python utils/name_sanitizer.py   (or call build_name_map())"
        )
    original_to_safe: dict = json.loads(map_path.read_text(encoding="utf-8"))
    safe_to_original: dict = {v: k for k, v in original_to_safe.items()}
    return original_to_safe, safe_to_original


# =============================================================================
# CLI entry point — run directly to build the map from teams.txt
# Usage: python utils/name_sanitizer.py [teams_file] [output_file]
# =============================================================================

if __name__ == "__main__":
    teams_file = sys.argv[1] if len(sys.argv) > 1 else "teams.txt"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "team_name_map.json"

    try:
        result = build_name_map(teams_file=teams_file, output=output_file)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Quick verification summary
    print(f"\nVerification:")
    print(f"  Total teams mapped : {len(result)}")
    print(f"  Unique safe names  : {len(set(result.values()))}")
    if len(result) != len(set(result.values())):
        print("  WARNING: safe name count != team count — collision logic may have a bug.")
    else:
        print("  All safe names are unique. ✓")