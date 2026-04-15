# utils/ollama_client.py
# All Ollama HTTP calls live here. Nothing else in the pipeline touches the API directly.
#
# Key design points from the blueprint (Sections 8.4, 8.5, 9):
#   - temperature=0.1 for factual extraction — not a creative task
#   - num_ctx=32768 to use qwen2.5-coder:14b's full context window
#   - repeat_penalty=1.1 to prevent silent repetition loops in output
#   - num_predict=4096 for per-chunk calls, 8192 for assembly calls (MUST NOT be swapped)
#   - ollama_assembly_call() is a named wrapper so callers can't accidentally forget 8192
#   - unload_model() releases VRAM between Phase 3 → Phase 4 model switch

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Lazily imported from config so this module stays importable before config exists.
# Each function that needs a config value reads it at call time.
def _cfg(name: str, default):
    """Pull a value from config.py, falling back to default if not set."""
    try:
        import config
        return getattr(config, name, default)
    except ModuleNotFoundError:
        return default


# --------------------------------------------------------------------------- #
# Core generation call                                                         #
# --------------------------------------------------------------------------- #

def ollama_generate(
    prompt: str,
    model: str,
    temperature: float = 0.1,
    num_ctx: int = 32768,
    num_predict: int = 4096,
) -> str | None:
    """
    Single synchronous call to Ollama's /api/generate endpoint.

    Parameters
    ----------
    prompt      : Full prompt string (instruction + code block already concatenated).
    model       : Ollama model tag, e.g. "qwen2.5-coder:14b".
    temperature : 0.1 default — low temp for factual extraction.
    num_ctx     : Context window size. Must match the model's actual window.
    num_predict : Max tokens to generate.
                  Use 4096 for per-chunk calls.
                  Use 8192 for assembly calls (via ollama_assembly_call).
                  Do NOT pass 4096 to assembly — output will be silently truncated.

    Returns
    -------
    Response string, or None if the request failed.
    """
    base_url = _cfg("OLLAMA_BASE_URL", "http://localhost:11434")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "repeat_penalty": 1.1,          # prevents silent repetition loops
            "stop": ["<|im_end|>", "### END", "---END---"],
        },
    }

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=300,    # 5-minute hard timeout per call
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.exceptions.Timeout:
        logger.error("ollama_generate timed out after 300s (model=%s)", model)
        return None
    except requests.exceptions.ConnectionError:
        logger.error(
            "Cannot connect to Ollama at %s — is it running?", base_url
        )
        return None
    except Exception as exc:
        logger.error("ollama_generate failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Retry wrapper — used for all per-chunk calls                                #
# --------------------------------------------------------------------------- #

def ollama_generate_with_retry(
    prompt: str,
    model: str,
    max_retries: int = 3,
    num_predict: int = 4096,
    temperature: float = 0.1,
) -> str | None:
    """
    Retries ollama_generate up to max_retries times.

    A response shorter than 100 characters is treated as a failure — the model
    either produced nothing useful or returned an error string.

    Sleeps 10 seconds between attempts to give Ollama time to recover.

    Parameters
    ----------
    num_predict : Forwarded to ollama_generate. Default 4096 for chunk calls.
                  Pass 8192 when calling through ollama_assembly_call().
    """
    for attempt in range(1, max_retries + 1):
        result = ollama_generate(
            prompt,
            model,
            temperature=temperature,
            num_predict=num_predict,
        )

        if result is None:
            logger.warning("Attempt %d/%d: call returned None.", attempt, max_retries)
        elif len(result.strip()) < 100:
            logger.warning(
                "Attempt %d/%d: response too short (%d chars) — retrying.",
                attempt, max_retries, len(result.strip()),
            )
        else:
            return result   # success

        if attempt < max_retries:
            logger.info("Sleeping 10s before retry %d...", attempt + 1)
            time.sleep(10)

    logger.error(
        "All %d attempts failed for model=%s. Returning None.", max_retries, model
    )
    return None     # caller marks this team as 'failed' in manifest


# --------------------------------------------------------------------------- #
# Assembly wrapper — MUST use num_predict=8192                                #
# --------------------------------------------------------------------------- #

def ollama_assembly_call(prompt: str, model: str) -> str | None:
    """
    Dedicated wrapper for the final assembly call that produces the full .md file.

    WHY THIS EXISTS (Section 8.5 / Reviewer 3 bug fix):
    The assembly output includes the full structured report including Replication Notes,
    which regularly exceeds 4096 tokens. Truncation is silent — the file just ends
    mid-sentence with no error. This wrapper hard-codes num_predict=8192 so it is
    impossible to accidentally forget the override when calling from 03_review_repos.py.

    Do NOT replace this with a bare ollama_generate_with_retry() call.
    """
    return ollama_generate_with_retry(
        prompt,
        model,
        max_retries=3,
        num_predict=8192,   # ← hard-coded, not a parameter — intentional
    )


# --------------------------------------------------------------------------- #
# Model memory management — Phase 3 → Phase 4 transition                     #
# --------------------------------------------------------------------------- #

def unload_model(model_name: str) -> None:
    """
    Explicitly release a model from Ollama's VRAM.

    Why this matters (Section 9):
    On a 16GB VRAM GPU, qwen2.5-coder:14b (~9GB) + mistral:7b (~5GB) = 14GB combined.
    Ollama keeps loaded models in VRAM between calls. Without this call before starting
    Phase 4, both models stay resident simultaneously, exceeding available VRAM and
    forcing layers to RAM — making synthesis very slow.

    Call this at the end of 03_review_repos.py before 04_synthesize.py starts.
    """
    base_url = _cfg("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        requests.post(
            f"{base_url}/api/generate",
            json={"model": model_name, "keep_alive": 0},
            timeout=30,
        )
        logger.info("Unloaded %s from VRAM.", model_name)
        print(f"Unloaded {model_name} from VRAM")
    except Exception as exc:
        logger.warning("Failed to unload %s: %s", model_name, exc)


# --------------------------------------------------------------------------- #
# Health check — useful at pipeline start                                     #
# --------------------------------------------------------------------------- #

def check_ollama_available(model: str | None = None) -> bool:
    """
    Returns True if Ollama is reachable. Optionally checks that a specific model
    is available in the local model list.

    Call this at the top of run_all.py or 03_review_repos.py to fail fast
    instead of discovering connectivity problems after 30 minutes of cloning.
    """
    base_url = _cfg("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        if model is not None:
            available = [m["name"] for m in resp.json().get("models", [])]
            if not any(m.startswith(model.split(":")[0]) for m in available):
                logger.error(
                    "Model '%s' not found in Ollama. Run: ollama pull %s", model, model
                )
                return False
        return True
    except Exception as exc:
        logger.error("Ollama not reachable at %s: %s", base_url, exc)
        return False
