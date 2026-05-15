"""
pipeline/scribe.py — the reports department.

Two LLM heads, one module:
  - DeepSeek (local GGUF, llama-cpp-python) — daily reports
  - Claude   (Anthropic API)                 — weekly reports

Both are lazy-loaded: the heavy DeepSeek file (~5 GB) is only mmapped
into memory the first time ask_deepseek() is called.
"""

import os
import re
import sys
import logging

sys.path.insert(0, "D:/Kestrel")

from config import ROOT, ANTHROPIC_API_KEY

LOG_PATH = os.path.join(ROOT, "logs/scribe.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.scribe")

# --- DeepSeek ---
DEEPSEEK_MODEL_PATH = os.path.join(
    ROOT, "models/deepseek/DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf"
)
DEEPSEEK_N_CTX     = 8192
DEEPSEEK_N_THREADS = max(os.cpu_count() - 1, 1)

# --- Claude ---
CLAUDE_MODEL      = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 5000

# --- Lazy singletons ---
_deepseek = None
_claude   = None

def _get_deepseek():
    """Load the DeepSeek GGUF on first use. ~10 sec warm-up."""
    global _deepseek
    if _deepseek is not None:
        return _deepseek

    if not os.path.exists(DEEPSEEK_MODEL_PATH):
        raise FileNotFoundError(
            f"DeepSeek GGUF not found at {DEEPSEEK_MODEL_PATH}. "
            f"Download from HuggingFace into D:/Kestrel/models/deepseek/."
        )

    from llama_cpp import Llama
    log.info(f"Loading DeepSeek: {os.path.basename(DEEPSEEK_MODEL_PATH)}...")
    _deepseek = Llama(
        model_path = DEEPSEEK_MODEL_PATH,
        n_ctx      = DEEPSEEK_N_CTX,
        n_threads  = DEEPSEEK_N_THREADS,
        verbose    = False
    )
    log.info(f"DeepSeek loaded (n_ctx={DEEPSEEK_N_CTX}, n_threads={DEEPSEEK_N_THREADS}).")
    return _deepseek

def _get_claude():
    """Lazy Anthropic client."""
    global _claude
    if _claude is not None:
        return _claude
    import anthropic
    _claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude

# --- R1 thinking-tag scrubber ---
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def _strip_reasoning(text):
    """R1-distill models emit <think>...</think> chains-of-thought. Drop them."""
    return _THINK_BLOCK.sub("", text).strip()

# --- Public API ---

def ask_deepseek(system, user, max_tokens=2000, temperature=0.4):
    """Call the local DeepSeek model. Returns response text or error string."""
    try:
        llm = _get_deepseek()
        out = llm.create_chat_completion(
            messages = [
                {"role": "system", "content": system},
                {"role": "user",   "content": user}
            ],
            max_tokens  = max_tokens,
            temperature = temperature
        )
        text = out['choices'][0]['message']['content']
        return _strip_reasoning(text)
    except Exception as e:
        log.error(f"DeepSeek call failed: {e}")
        return f"_DeepSeek unavailable: {e}_"

def ask_claude(system, user, max_tokens=CLAUDE_MAX_TOKENS):
    """Call the Anthropic Claude API. Returns response text or error string."""
    try:
        client  = _get_claude()
        message = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = max_tokens,
            messages   = [
                {"role": "user", "content": f"{system}\n\n{user}"}
            ]
        )
        return message.content[0].text
    except Exception as e:
        log.error(f"Claude call failed: {e}")
        return f"_Claude unavailable: {e}_"

# --- Smoke test ---
if __name__ == "__main__":
    log.info("=== SCRIBE SMOKE TEST ===")

    log.info("--- DeepSeek ---")
    out = ask_deepseek(
        system = "You are a concise trading analyst.",
        user   = "In one sentence, why might a stock open significantly higher in the morning than it closed the night before, even without any public news?",
        max_tokens = 200
    )
    print(f"DeepSeek: {out}\n")

    log.info("--- Claude ---")
    out = ask_claude(
        system = "You are a concise trading analyst.",
        user   = "In one sentence, why might a stock open significantly higher in the morning than it closed the night before, even without any public news?",
        max_tokens = 200
    )
    print(f"Claude: {out}\n")
