# utils/ollama_client.py
# All Ollama HTTP calls live here.
#
# BUG 9 FIX: check_ollama_available() used m.startswith(model.split(":")[0]) which passes
# if qwen2.5-coder:7b is installed but qwen2.5-coder:14b is required. Phase 3 would start,
# then fail on every single team with a cryptic model error. Fixed to exact tag match.

import logging
import time

import requests

logger = logging.getLogger(__name__)


def _cfg(name: str, default):
    try:
        import config
        return getattr(config, name, default)
    except ModuleNotFoundError:
        return default


def ollama_generate(
    prompt: str,
    model: str,
    temperature: float = 0.1,
    num_ctx: int = 32768,
    num_predict: int = 4096,
) -> str | None:
    base_url = _cfg("OLLAMA_BASE_URL", "http://localhost:11434")
    payload = {
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
    }

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.exceptions.Timeout:
        logger.error("ollama_generate timed out after 300s (model=%s)", model)
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to Ollama at %s — is it running?", base_url)
        return None
    except Exception as exc:
        logger.error("ollama_generate failed: %s", exc)
        return None


def ollama_generate_with_retry(
    prompt: str,
    model: str,
    max_retries: int = 3,
    num_predict: int = 4096,
    temperature: float = 0.1,
) -> str | None:
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
            return result

        if attempt < max_retries:
            logger.info("Sleeping 10s before retry %d...", attempt + 1)
            time.sleep(10)

    logger.error("All %d attempts failed for model=%s. Returning None.", max_retries, model)
    return None


def ollama_assembly_call(prompt: str, model: str) -> str | None:
    """
    Dedicated wrapper for the final assembly call.
    Hard-codes num_predict=8192 — assembly output routinely exceeds 4096 tokens
    and truncation is silent. Do NOT replace with a bare ollama_generate_with_retry() call.
    """
    return ollama_generate_with_retry(
        prompt,
        model,
        max_retries=3,
        num_predict=8192,  # hard-coded intentionally
    )


def unload_model(model_name: str) -> None:
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


def check_ollama_available(model: str | None = None) -> bool:
    """
    BUG 9 FIX: Original used m.startswith(model.split(":")[0]) — this passes when
    qwen2.5-coder:7b is installed but qwen2.5-coder:14b is required, causing Phase 3
    to start and then fail cryptically on every team. Now uses exact tag match.
    """
    base_url = _cfg("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        if model is not None:
            available = [m["name"] for m in resp.json().get("models", [])]
            if model not in available:
                logger.error(
                    "Model '%s' not found in Ollama. Available: %s\nRun: ollama pull %s",
                    model, available, model,
                )
                return False
        return True
    except Exception as exc:
        logger.error("Ollama not reachable at %s: %s", base_url, exc)
        return False
