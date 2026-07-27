"""
One function, two real backends plus an offline fallback.

Set LLM_PROVIDER to gemini (default), ollama, or none. Everything downstream
calls llm.complete(prompt) and does not care which one is live.

Gemini (Google's API, GEMINI_API_KEY) is the only cloud provider this build
supports. There is no Anthropic path: if LLM_PROVIDER=anthropic is set, the
agent explains why and falls back to templated commentary instead of calling
a different vendor's API behind your back.

If no provider is configured the agent still runs end to end and produces the
full report. It just falls back to templated commentary instead of written
commentary. Every number in the report comes from burn.py either way, so the
numbers are identical with or without a model. That is on purpose: the model
writes the words, it does not compute the figures.
"""

import os
import textwrap
import time

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.1:8b",
}

# Providers this build understands but refuses to call, with a reason why.
UNSUPPORTED_PROVIDERS = {
    "anthropic": (
        "this build only talks to Google's API. Set LLM_PROVIDER=gemini and "
        "GEMINI_API_KEY (or LLM_PROVIDER=none to skip the model)."
    ),
}

MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 2  # exponential backoff: 2s, 4s

# Substrings of transient provider errors worth a retry (rate limits,
# overload, flaky network). Anything else - bad key, bad request - fails fast.
_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504",
    "rate limit", "resource_exhausted", "unavailable", "overloaded",
    "timeout", "timed out", "temporarily",
)


class LLM:
    def __init__(self, provider=None, model=None):
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "gemini").lower()
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(self.provider)
        self._client = None
        self.reason = None
        self.available = self._init()

    def _init(self):
        if self.provider == "none":
            self.reason = "provider set to none"
            return False

        if self.provider in UNSUPPORTED_PROVIDERS:
            self.reason = UNSUPPORTED_PROVIDERS[self.provider]
            return False

        try:
            if self.provider == "gemini":
                if not os.getenv("GEMINI_API_KEY"):
                    self.reason = "GEMINI_API_KEY not set"
                    return False
                from google import genai
                self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
                return True

            if self.provider == "ollama":
                import ollama
                self._client = ollama
                return True

        except ImportError as e:
            self.reason = f"missing package for {self.provider}: {e.name}"
            return False

        self.reason = f"unknown provider {self.provider!r}"
        return False

    def complete(self, prompt, max_tokens=1200, temperature=0.4, json_mode=False):
        """Returns the model's text, or None if anything goes wrong.

        Retries transient failures (rate limits, brief outages) with
        exponential backoff before giving up. A bad key or bad request fails
        immediately - retrying that just burns time for the same error.
        """
        if not self.available:
            return None

        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._call(prompt, max_tokens, temperature, json_mode)
            except Exception as e:
                is_last = attempt == MAX_ATTEMPTS - 1
                if not is_last and _is_transient(e):
                    time.sleep(RETRY_BASE_SECONDS * (2 ** attempt))
                    continue
                print(f"llm: {self.provider} call failed ({type(e).__name__}: {e})")
                return None

    def _call(self, prompt, max_tokens, temperature, json_mode):
        if self.provider == "gemini":
            from google.genai import types
            config = types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
                response_mime_type="application/json" if json_mode else "text/plain",
            )
            r = self._client.models.generate_content(
                model=self.model, contents=prompt, config=config,
            )
            return r.text

        if self.provider == "ollama":
            r = self._client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json" if json_mode else None,
                options={"temperature": temperature},
            )
            return r["message"]["content"]

        return None

    def describe(self):
        if self.available:
            return f"{self.provider} / {self.model}"
        return f"none ({self.reason}) - report will use templated commentary"


def _is_transient(e):
    text = str(e).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def banner(llm):
    print(textwrap.dedent(f"""
    model:  {llm.describe()}
    """).strip())
