"""
src/04_synthesize.py — Phase 4: Knowledge Synthesis
Reads all reviews/*.md files, computes real frequency counts in Python,
then calls Ollama (mistral:7b) to write MASTER_PATTERNS.md and GAPS.md.
YOUR_FEATURE_PLAN.md is scaffolded with instructions for the manual Gemini step.

Run: python src/04_synthesize.py
"""

import json
import re
import sys
import time
import requests
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Config — import from config.py if available, otherwise use defaults
# ---------------------------------------------------------------------------
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import (
        OLLAMA_BASE_URL,
        SYNTHESIS_MODEL,
        CODE_REVIEW_MODEL,
    )
except ImportError:
    OLLAMA_BASE_URL = "http://localhost:11434"
    SYNTHESIS_MODEL = "mistral:7b"
    CODE_REVIEW_MODEL = "qwen2.5-coder:14b"

REVIEWS_DIR = Path("reviews")
KNOWLEDGE_DIR = Path("knowledge")
KNOWLEDGE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Known technology lookup list — seeds the frequency counter.
# Add more as needed; the regex fallback handles everything else.
# ---------------------------------------------------------------------------
KNOWN_TECHNOLOGIES = [
    # Frontend
    "React", "Vue", "Angular", "Next.js", "Nuxt", "Svelte", "TypeScript",
    "JavaScript", "HTML", "CSS", "Tailwind", "Bootstrap", "Material UI",
    "Vite", "Webpack", "Redux",
    # Backend
    "FastAPI", "Flask", "Django", "Spring Boot", "Express", "NestJS",
    "Rails", "Laravel", "ASP.NET", "Gin", "Fiber", "Actix",
    "Node.js", "Python", "Java", "Go", "Rust", "C#", "Ruby", "PHP", "Kotlin",
    # Databases
    "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "Elasticsearch",
    "DynamoDB", "Cassandra", "Firestore", "Supabase",
    # Cloud / Infra
    "Docker", "Kubernetes", "AWS", "GCP", "Azure", "Terraform",
    "GitHub Actions", "GitLab CI", "Jenkins",
    # AI / ML
    "OpenAI", "LangChain", "HuggingFace", "TensorFlow", "PyTorch", "scikit-learn",
    "Ollama", "Gemini", "Claude", "Anthropic",
    # Misc
    "GraphQL", "REST", "gRPC", "WebSocket", "Celery", "RabbitMQ", "Kafka",
    "Nginx", "Gunicorn", "Uvicorn", "SQLAlchemy", "Prisma", "Drizzle",
    "JWT", "OAuth", "Auth0",
]

GUIDEWIRE_KEYWORDS = [
    "ClaimCenter", "PolicyCenter", "BillingCenter", "ContactManager",
    "InsuranceSuite", "Cloud API", "Integration Framework", "Gosu",
    "OOTB", "PCF", "Guidewire Cloud", "Data Platform", "Jutro",
    "AppExchange", "Predictive Analytics", "Cyence",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_section(md_content: str, section_header: str) -> str:
    """Extract content between section_header and the next ## header."""
    pattern = rf'{re.escape(section_header)}\n(.*?)(?=\n## |\Z)'
    match = re.search(pattern, md_content, re.DOTALL)
    return match.group(1).strip() if match else ''


def extract_bullet_items(text: str) -> list[str]:
    """Return non-empty lines that look like bullet items."""
    items = []
    for line in text.splitlines():
        line = line.strip().lstrip('-*•').strip()
        if line and line.upper() != 'NOT FOUND':
            items.append(line)
    return items


def unload_model(model_name: str):
    """Force Ollama to release a model from VRAM (keep_alive=0)."""
    try:
        requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model_name, "keep_alive": 0},
            timeout=30,
        )
        print(f"[VRAM] Unloaded {model_name}")
    except Exception as e:
        print(f"[VRAM] Could not unload {model_name}: {e}")


def ollama_generate(
    prompt: str,
    model: str,
    temperature: float = 0.3,
    num_ctx: int = 32768,
    num_predict: int = 4096,
) -> str | None:
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": num_ctx,
                    "num_predict": num_predict,
                    "repeat_penalty": 1.1,
                    "stop": ["<|im_end|>", "### END", "---END---"],
                },
            },
            timeout=600,
        )
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"  [Ollama error] {e}")
        return None


def ollama_generate_with_retry(
    prompt: str,
    model: str,
    max_retries: int = 3,
    num_predict: int = 4096,
) -> str | None:
    for attempt in range(max_retries):
        result = ollama_generate(prompt, model, num_predict=num_predict)
        if result and len(result.strip()) > 100:
            return result
        print(f"  Attempt {attempt + 1}/{max_retries}: response too short, retrying...")
        time.sleep(10)
    return None


# ---------------------------------------------------------------------------
# Step 1 — Parse all review .md files
# ---------------------------------------------------------------------------

def load_all_reviews() -> list[dict]:
    """Return a list of dicts, one per review file."""
    records = []
    for md_file in sorted(REVIEWS_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            records.append(
                {
                    "file": md_file.name,
                    "tech_stack": extract_section(content, "## Tech Stack"),
                    "features": extract_section(content, "## Core Features Implemented"),
                    "notable": extract_section(content, "## Notable Technical Choices"),
                    "guidewire": extract_section(content, "## Guidewire Integration"),
                    "api_surface": extract_section(content, "## API Surface"),
                }
            )
        except Exception as e:
            print(f"  [WARN] Could not read {md_file.name}: {e}")
    print(f"[PARSE] Loaded {len(records)} review files from {REVIEWS_DIR}/")
    return records


# ---------------------------------------------------------------------------
# Step 2 — Code-driven frequency analysis
# ---------------------------------------------------------------------------

def build_tech_freq(records: list[dict]) -> Counter:
    """Count exact technology mentions across all tech stack sections."""
    freq: Counter = Counter()
    for record in records:
        text = record["tech_stack"].lower()
        for tech in KNOWN_TECHNOLOGIES:
            if tech.lower() in text:
                freq[tech] += 1
        # Also pick up any bullet items not in the known list
        for item in extract_bullet_items(record["tech_stack"]):
            # Short items that look like proper-noun tech names
            if 2 < len(item) < 40 and item not in KNOWN_TECHNOLOGIES:
                freq[item] += 1
    return freq


def build_feature_freq(records: list[dict]) -> Counter:
    """Rough frequency of feature keywords across all feature sections."""
    freq: Counter = Counter()
    for record in records:
        for item in extract_bullet_items(record["features"]):
            # Normalise to lower-case first 60 chars to collapse near-duplicates
            key = item.lower()[:60]
            freq[key] += 1
    return freq


def build_guidewire_freq(records: list[dict]) -> Counter:
    """Count Guidewire product/API keyword mentions."""
    freq: Counter = Counter()
    for record in records:
        section_text = record["guidewire"] + " " + record["api_surface"]
        if section_text.strip().upper() == "NOT FOUND":
            continue
        for kw in GUIDEWIRE_KEYWORDS:
            if kw.lower() in section_text.lower():
                freq[kw] += 1
    return freq


def build_rare_items(records: list[dict], total: int, threshold_pct: float = 0.15) -> dict:
    """
    Extract low-frequency items from three sections:
      - Notable Technical Choices
      - Guidewire Integration
      - API Surface
    threshold_pct: items appearing in fewer than this fraction of teams are 'rare'.
    """
    max_count = max(1, int(total * threshold_pct))

    notable_freq: Counter = Counter()
    gw_item_freq: Counter = Counter()
    api_freq: Counter = Counter()

    for record in records:
        for item in extract_bullet_items(record["notable"]):
            notable_freq[item.lower()[:80]] += 1
        for item in extract_bullet_items(record["guidewire"]):
            gw_item_freq[item.lower()[:80]] += 1
        for item in extract_bullet_items(record["api_surface"]):
            api_freq[item.lower()[:80]] += 1

    rare_notable = {k: v for k, v in notable_freq.items() if v <= max_count}
    rare_guidewire = {k: v for k, v in gw_item_freq.items() if v <= max_count}
    rare_api = {k: v for k, v in api_freq.items() if v <= max_count}

    return {
        "rare_notable": rare_notable,
        "rare_guidewire": rare_guidewire,
        "rare_api": rare_api,
    }


# ---------------------------------------------------------------------------
# Step 3 — Generate MASTER_PATTERNS.md
# ---------------------------------------------------------------------------

def generate_master_patterns(
    tech_freq: Counter,
    feature_freq: Counter,
    guidewire_freq: Counter,
    total: int,
) -> bool:
    output_path = KNOWLEDGE_DIR / "MASTER_PATTERNS.md"
    print(f"\n[SYNTHESIS] Generating MASTER_PATTERNS.md via {SYNTHESIS_MODEL}...")

    prompt = f"""You are writing a competitive analysis report.
The data below contains EXACT frequency counts — computed by code, not estimated.
Total teams analysed: {total}

TECH STACK FREQUENCIES (number of teams using each technology):
{json.dumps(dict(tech_freq.most_common(60)), indent=2)}

FEATURE FREQUENCIES (approximate, from text analysis of feature sections):
{json.dumps(dict(feature_freq.most_common(40)), indent=2)}

GUIDEWIRE API USAGE (number of teams using each Guidewire product/API):
{json.dumps(dict(guidewire_freq.most_common()), indent=2)}

Write MASTER_PATTERNS.md with EXACTLY these five sections (use markdown ## headers):

## Table Stakes
Technologies or patterns used by more than 60% of teams ({int(total * 0.6)}+ teams).
These are baseline expectations — do NOT differentiate on them. List each with its count.

## Common Choices
Technologies or patterns used by 30–60% of teams ({int(total * 0.3)}–{int(total * 0.6)} teams).
Worth knowing but not strongly differentiating.

## Minority Choices
Technologies used by 10–30% of teams ({int(total * 0.1)}–{int(total * 0.3)} teams).
Implementing these shows breadth without being novel.

## Guidewire API Coverage
Which Guidewire APIs appear most and least often across all teams.
Explain what the distribution implies about what judges will expect to see.

## Average Completeness Assessment
Based on the feature frequencies and tech spread, what is the estimated average
completeness level of competing teams? Low / Medium / High? Give a 2–3 sentence
reasoning with supporting numbers from the data above.
"""

    result = ollama_generate_with_retry(prompt, SYNTHESIS_MODEL, num_predict=4096)
    if not result:
        print("  [ERROR] MASTER_PATTERNS.md generation failed.")
        return False

    output_path.write_text(result, encoding="utf-8")
    print(f"  Written: {output_path}")
    return True


# ---------------------------------------------------------------------------
# Step 4 — Generate GAPS.md
# ---------------------------------------------------------------------------

def generate_gaps(rare_items: dict, total: int) -> bool:
    output_path = KNOWLEDGE_DIR / "GAPS.md"
    print(f"\n[SYNTHESIS] Generating GAPS.md via {SYNTHESIS_MODEL}...")

    rare_notable_str = "\n".join(
        f"  - {k} (used by {v} team{'s' if v != 1 else ''})"
        for k, v in sorted(rare_items["rare_notable"].items(), key=lambda x: x[1])[:50]
    ) or "  (none found)"

    rare_guidewire_str = "\n".join(
        f"  - {k} (used by {v} team{'s' if v != 1 else ''})"
        for k, v in sorted(rare_items["rare_guidewire"].items(), key=lambda x: x[1])[:30]
    ) or "  (none found — most teams likely did not use Guidewire-specific APIs)"

    rare_api_str = "\n".join(
        f"  - {k} (used by {v} team{'s' if v != 1 else ''})"
        for k, v in sorted(rare_items["rare_api"].items(), key=lambda x: x[1])[:30]
    ) or "  (none found)"

    prompt = f"""You are writing a competitive gap analysis for a hackathon competitor.
Total teams analysed: {total}
The items below appear in fewer than 15% of teams — they are rare implementation choices.
Rare = potential differentiation opportunity.

LOW-FREQUENCY NOTABLE TECHNICAL CHOICES (from ## Notable Technical Choices sections):
{rare_notable_str}

LOW-FREQUENCY GUIDEWIRE APIS (from ## Guidewire Integration and ## API Surface sections):
{rare_guidewire_str}

LOW-FREQUENCY API PATTERNS (from ## API Surface sections):
{rare_api_str}

Write GAPS.md with EXACTLY these sections (use markdown ## headers):

## Rare Technical Choices Analysis
For each rare item from Notable Technical Choices, write one bullet:
  - **Item name**: Plain-English explanation | Complexity: Low/Medium/High | Judge impact: Low/Medium/High | Why rare?

## Rare Guidewire Integration Opportunities
For each rare Guidewire API/product, write one bullet in the same format as above.
This is the HIGHEST-VALUE section — rare Guidewire API usage is the top differentiator
in a Guidewire hackathon.

## Rare API Patterns
For each rare API pattern, write one bullet in the same format.

## Top 10 Differentiation Opportunities
Ranked list of the 10 best items to build, ranked by:
  (high judge impact × low or medium implementation complexity)
For each: brief name, why it differentiates, realistic complexity estimate.

## Key Insight Summary
2–3 paragraphs synthesising the most important patterns in this gap analysis.
What story does the data tell about where the competition is weak?
"""

    result = ollama_generate_with_retry(prompt, SYNTHESIS_MODEL, num_predict=4096)
    if not result:
        print("  [ERROR] GAPS.md generation failed.")
        return False

    output_path.write_text(result, encoding="utf-8")
    print(f"  Written: {output_path}")
    return True


# ---------------------------------------------------------------------------
# Step 5 — Scaffold YOUR_FEATURE_PLAN.md (manual Gemini step)
# ---------------------------------------------------------------------------

def scaffold_feature_plan():
    output_path = KNOWLEDGE_DIR / "YOUR_FEATURE_PLAN.md"
    print(f"\n[SCAFFOLD] Writing YOUR_FEATURE_PLAN.md template...")

    gaps_content = ""
    gaps_path = KNOWLEDGE_DIR / "GAPS.md"
    if gaps_path.exists():
        gaps_content = gaps_path.read_text(encoding="utf-8")

    template = f"""# YOUR_FEATURE_PLAN.md
## How to complete this file

This file requires a **manual Gemini step** (see Section 7.4 of the blueprint).
GAPS.md has been generated automatically. Your task:

1. Write a ~500-word description of your current repo state below.
2. Copy the prompt below (with GAPS.md filled in) into Gemini Pro or Flash.
3. Paste Gemini's response here and delete this instruction block.

---

## Your Current Repo Description (fill this in manually)

<!-- Describe what you have built so far. ~500 words.
     Cover: tech stack, features implemented, what's working, what's stubbed.
     Be specific — Gemini will use this to tailor its recommendations. -->

YOUR_REPO_DESCRIPTION_HERE

---

## Gemini Prompt to Use

```
I am competing in the Guidewire DEVTrails 2026 hackathon.
I have completed competitive intelligence analysis of all 265 competing teams.

HERE IS WHAT MOST TEAMS ARE NOT BUILDING (GAPS.md):
{gaps_content[:4000]}
[...truncated — paste the full GAPS.md content here...]

HERE IS MY CURRENT IMPLEMENTATION:
[paste YOUR_REPO_DESCRIPTION_HERE content]

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

## Gemini's Response (paste here after running the prompt above)

<!-- Paste Gemini's output here -->
"""

    output_path.write_text(template, encoding="utf-8")
    print(f"  Written: {output_path} (manual Gemini step required)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Phase 4 — Knowledge Synthesis")
    print("=" * 60)

    # Step 0: Unload Phase 3 model from VRAM before loading synthesis model
    print(f"\n[VRAM] Unloading {CODE_REVIEW_MODEL} to free VRAM for synthesis model...")
    unload_model(CODE_REVIEW_MODEL)
    time.sleep(2)

    # Step 1: Parse all review files
    if not REVIEWS_DIR.exists():
        print(f"[ERROR] {REVIEWS_DIR}/ does not exist. Run Phase 3 first.")
        sys.exit(1)

    records = load_all_reviews()
    total = len(records)
    if total == 0:
        print("[ERROR] No review files found. Run Phase 3 first.")
        sys.exit(1)

    # Step 2: Code-driven frequency analysis
    print(f"\n[FREQ] Computing frequency counts across {total} review files...")
    tech_freq = build_tech_freq(records)
    feature_freq = build_feature_freq(records)
    guidewire_freq = build_guidewire_freq(records)
    rare_items = build_rare_items(records, total)

    # Print quick summary
    print(f"  Top 10 technologies: {dict(tech_freq.most_common(10))}")
    print(f"  Guidewire keyword hits: {dict(guidewire_freq.most_common())}")
    print(
        f"  Rare items found — notable: {len(rare_items['rare_notable'])}, "
        f"guidewire: {len(rare_items['rare_guidewire'])}, "
        f"api: {len(rare_items['rare_api'])}"
    )

    # Persist raw frequency data for debugging / re-runs
    freq_cache_path = KNOWLEDGE_DIR / "freq_cache.json"
    freq_cache = {
        "total_teams": total,
        "tech_freq": dict(tech_freq),
        "feature_freq": dict(feature_freq),
        "guidewire_freq": dict(guidewire_freq),
        "rare_notable": rare_items["rare_notable"],
        "rare_guidewire": rare_items["rare_guidewire"],
        "rare_api": rare_items["rare_api"],
    }
    freq_cache_path.write_text(json.dumps(freq_cache, indent=2), encoding="utf-8")
    print(f"\n[CACHE] Frequency data saved to {freq_cache_path}")

    # Step 3: Generate MASTER_PATTERNS.md
    master_ok = generate_master_patterns(tech_freq, feature_freq, guidewire_freq, total)

    # Step 4: Generate GAPS.md
    gaps_ok = generate_gaps(rare_items, total)

    # Step 5: Scaffold YOUR_FEATURE_PLAN.md
    scaffold_feature_plan()

    # Summary
    print("\n" + "=" * 60)
    print("Phase 4 Complete")
    print("=" * 60)
    print(f"  knowledge/MASTER_PATTERNS.md : {'✓' if master_ok else '✗ FAILED'}")
    print(f"  knowledge/GAPS.md            : {'✓' if gaps_ok else '✗ FAILED'}")
    print(f"  knowledge/YOUR_FEATURE_PLAN.md: ✓ (needs manual Gemini step)")
    print(f"  knowledge/freq_cache.json    : ✓ (raw frequency data)")
    print()

    if not master_ok or not gaps_ok:
        print("[WARN] One or more files failed. Check Ollama is running:")
        print(f"  curl {OLLAMA_BASE_URL}/api/tags")
        sys.exit(1)


if __name__ == "__main__":
    main()
