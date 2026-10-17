"""
llm_client.py — Provider-agnostic LLM interface for AIEdS
==========================================================
Switch LLM provider by setting LLM_PROVIDER in your .env file:

  LLM_PROVIDER=groq    →  Groq API — FREE tier, no credit card, fast Llama models
  LLM_PROVIDER=claude  →  Anthropic Claude API (paid, very cheap)
  LLM_PROVIDER=ollama  →  Local Ollama server (requires Ollama installed & running)

All callers use:
    from llm_client import stream_llm, chat_llm, analyze_image_llm

Stream usage (inside a Streamlit st.write_stream generator):
    def my_gen():
        for text in stream_llm(messages):
            yield text
    full_text = st.write_stream(my_gen())

Non-streaming:
    reply = chat_llm(messages)

Image analysis (OCR / caption):
    reply = analyze_image_llm(img_b64, prompt)
"""

import os
import logging
from dotenv import load_dotenv

# Load .env from the login folder (works whether called from login/ or login/pages/)
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

LLM_PROVIDER  = os.getenv("LLM_PROVIDER",  "groq").strip().lower()

# Groq settings
GROQ_API_KEY  = os.getenv("GROQ_API_KEY",  "")
GROQ_MODEL    = os.getenv("GROQ_MODEL",    "llama-3.1-8b-instant")

# Claude / Anthropic settings
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL  = os.getenv("CLAUDE_MODEL",  "claude-3-5-haiku-20241022")
CLAUDE_VISION = os.getenv("CLAUDE_VISION_MODEL", "claude-3-5-sonnet-20241022")

# Ollama settings
OLLAMA_HOST   = os.getenv("OLLAMA_HOST",   "http://127.0.0.1:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL",  "llama3.2:3b-instruct-q4_K_M")

log = logging.getLogger(__name__)


# ── Lazy singletons ────────────────────────────────────────────────────────────

_groq_client      = None
_anthropic_client = None
_ollama_client    = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq
            _groq_client = Groq(api_key=GROQ_API_KEY)
        except ImportError:
            raise RuntimeError(
                "groq package not installed. Run: pip install groq"
            )
    return _groq_client


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        try:
            import anthropic
            _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
    return _anthropic_client


def _get_ollama():
    global _ollama_client
    if _ollama_client is None:
        try:
            from ollama import Client
            from httpx import Timeout
            _ollama_client = Client(host=OLLAMA_HOST, timeout=Timeout(120.0))
        except ImportError:
            raise RuntimeError(
                "ollama package not installed. Run: pip install ollama"
            )
    return _ollama_client


# ── Message normalisation ──────────────────────────────────────────────────────

def _split_system(messages: list) -> tuple[str, list]:
    """
    Separates system message from user/assistant messages.
    Claude requires system as a top-level parameter, not inside messages[].
    """
    system = ""
    rest   = []
    for m in messages:
        if m.get("role") == "system":
            system = m.get("content", "")
        else:
            rest.append(m)
    return system, rest


def _ensure_alternating(messages: list) -> list:
    """
    Claude requires strictly alternating user/assistant turns starting with user.
    Merges consecutive same-role messages and fixes ordering.
    """
    if not messages:
        return [{"role": "user", "content": "Hello"}]
    merged = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["content"]
        else:
            merged.append({"role": m["role"], "content": m["content"]})
    if merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "Hello"})
    return merged


# ── Core public API ────────────────────────────────────────────────────────────

def stream_llm(messages: list):
    """
    Generator — yields text chunks from the active LLM provider.
    messages = list of {"role": "system"|"user"|"assistant", "content": "..."}
    """
    if LLM_PROVIDER == "groq":
        yield from _stream_groq(messages)
    elif LLM_PROVIDER == "ollama":
        yield from _stream_ollama(messages)
    elif LLM_PROVIDER == "claude":
        yield from _stream_claude(messages)
    else:
        yield f"[Configuration error: unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use groq, claude, or ollama]"


def chat_llm(messages: list) -> str:
    """Non-streaming — collects all chunks and returns the full response string."""
    return "".join(stream_llm(messages))


def analyze_image_llm(img_b64: str, prompt: str, media_type: str = "image/jpeg") -> str:
    """
    Send an image + text prompt to the LLM. Returns full response string.
    img_b64    — base64-encoded image bytes (no data-URI prefix).
    media_type — e.g. "image/jpeg", "image/png".

    Note: Groq's free tier does not support image input (vision).
    When using Groq, image analysis falls back to a text-only response.
    For vision, use LLM_PROVIDER=claude or LLM_PROVIDER=ollama.
    """
    if LLM_PROVIDER == "groq":
        return _analyze_image_groq(img_b64, prompt)
    elif LLM_PROVIDER == "ollama":
        return _analyze_image_ollama(img_b64, prompt)
    else:
        return _analyze_image_claude(img_b64, prompt, media_type)


# ── Groq backend ───────────────────────────────────────────────────────────────

def _stream_groq(messages: list):
    if not GROQ_API_KEY:
        yield "[Configuration error: GROQ_API_KEY is not set in your .env file. Get a free key at console.groq.com]"
        return
    client = _get_groq()
    try:
        # Groq accepts system messages inside the messages list (OpenAI-compatible)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.0,
            max_tokens=2048,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as e:
        log.error("Groq stream error: %s", e)
        yield f"\n\n[LLM Error — Groq: {e}]"


def _analyze_image_groq(img_b64: str, prompt: str) -> str:
    """
    Groq's free tier text models don't support image input.
    We acknowledge the image and ask the LLM to respond based on the prompt text alone.
    For full vision support switch to LLM_PROVIDER=claude.
    """
    if not GROQ_API_KEY:
        return "[Configuration error: GROQ_API_KEY is not set in your .env file]"
    client = _get_groq()
    try:
        fallback_prompt = (
            f"{prompt}\n\n"
            "[Note: An image was provided but the current LLM provider (Groq free tier) "
            "does not support image input. Please describe the image content manually, "
            "or switch to LLM_PROVIDER=claude for full vision capability.]"
        )
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": fallback_prompt}],
            temperature=0.0,
            max_tokens=512,
            stream=False,
        )
        return resp.choices[0].message.content
    except Exception as e:
        log.error("Groq image fallback error: %s", e)
        return f"[Image analysis not supported on Groq free tier. Switch to LLM_PROVIDER=claude for vision. Error: {e}]"


# ── Claude backend ─────────────────────────────────────────────────────────────

def _stream_claude(messages: list):
    if not ANTHROPIC_KEY:
        yield "[Configuration error: ANTHROPIC_API_KEY is not set in your .env file]"
        return
    client  = _get_anthropic()
    system, user_msgs = _split_system(messages)
    cleaned = _ensure_alternating(user_msgs)
    kwargs  = dict(model=CLAUDE_MODEL, max_tokens=2048, messages=cleaned)
    if system:
        kwargs["system"] = system
    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as e:
        log.error("Claude stream error: %s", e)
        yield f"\n\n[LLM Error — Claude: {e}]"


def _analyze_image_claude(img_b64: str, prompt: str, media_type: str) -> str:
    if not ANTHROPIC_KEY:
        return "[Configuration error: ANTHROPIC_API_KEY is not set in your .env file]"
    client = _get_anthropic()
    try:
        resp = client.messages.create(
            model=CLAUDE_VISION,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64",
                                "media_type": media_type,
                                "data": img_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.content[0].text
    except Exception as e:
        log.error("Claude image error: %s", e)
        return f"[Image analysis failed — Claude: {e}]"


# ── Ollama backend ─────────────────────────────────────────────────────────────

def _stream_ollama(messages: list):
    client = _get_ollama()
    try:
        resp = client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            stream=True,
            keep_alive=-1,
            options={"num_gpu": 50, "temperature": 0.0, "num_ctx": 2048},
        )
        for chunk in resp:
            yield chunk["message"]["content"]
    except Exception as e:
        log.error("Ollama stream error: %s", e)
        yield f"\n\n[LLM Error — Ollama: {e}]"


def _analyze_image_ollama(img_b64: str, prompt: str) -> str:
    client       = _get_ollama()
    vision_model = os.getenv("OLLAMA_VISION_MODEL", "llava:7b")
    try:
        resp = client.chat(
            model=vision_model,
            messages=[{"role": "user", "content": prompt, "images": [img_b64]}],
        )
        return resp["message"]["content"]
    except Exception as e:
        log.error("Ollama image error: %s", e)
        return f"[Image analysis failed — Ollama: {e}]"


# ── Utility ────────────────────────────────────────────────────────────────────

def provider_label() -> str:
    """Short human-readable label of the active provider — shown in the chatbot UI."""
    if LLM_PROVIDER == "groq":
        return f"Groq · {GROQ_MODEL}"
    if LLM_PROVIDER == "ollama":
        return f"Ollama · {OLLAMA_MODEL}"
    return f"Claude · {CLAUDE_MODEL}"
