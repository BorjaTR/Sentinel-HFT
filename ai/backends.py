"""Pluggable backends for AI-powered root-cause explanations.

Three backends are supported, selected via ``SENTINEL_AI_BACKEND`` or the
``--ai-backend`` CLI flag:

- ``deterministic`` — template-driven RCA from :class:`FactSet` +
  :class:`PatternDetectionResult`. Zero network, zero dependencies, always
  works. This is the safest default for prop-desk / compliance-sensitive
  environments.
- ``ollama`` — local LLM over HTTP (``http://localhost:11434`` by default).
  Supports any model the user has pulled (``llama3.1:8b``, ``qwen2.5:7b``,
  etc.). No traces leave the machine.
- ``anthropic`` — Claude API via the official SDK. Requires
  ``ANTHROPIC_API_KEY``. Only use where third-party data egress is
  acceptable. Disabled by default.

The ``auto`` selector prefers ``deterministic`` (guaranteed to work) and
only reaches for an LLM if one is explicitly requested. This is a
deliberate reversal of earlier versions where Anthropic was the hard
default.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class BackendUnavailable(RuntimeError):
    """Raised when a requested backend cannot be used (missing deps, no key)."""


@dataclass
class BackendResponse:
    """Raw response from a backend — text plus provenance metadata."""

    text: str
    backend: str
    model: Optional[str] = None
    # True iff the response data never left the local machine.
    offline: bool = True


class Backend(ABC):
    """Abstract LLM-ish backend that turns a prompt into text."""

    name: str = "abstract"
    offline: bool = True

    @abstractmethod
    def available(self) -> bool:
        """Return True iff this backend can serve a call right now."""

    @abstractmethod
    def generate(self, system: str, prompt: str, *, max_tokens: int = 1024,
                 temperature: float = 0.3) -> BackendResponse:
        """Produce text for ``prompt`` under ``system`` instructions."""


# ---------------------------------------------------------------------------
# Deterministic (no LLM) — default, always available
# ---------------------------------------------------------------------------

class DeterministicBackend(Backend):
    """Rule-based RCA that emits the same four-section shape as the LLM
    backends, grounded only on the ``FACTS`` block in the prompt.

    This is not a summary of the prompt — it is a structured extraction
    of what the ``FactExtractor`` already knows, written in the format
    downstream parsers expect. It is deliberately conservative: if the
    facts don't support a claim, we don't make the claim.
    """

    name = "deterministic"
    offline = True

    def available(self) -> bool:
        return True

    def generate(self, system: str, prompt: str, *, max_tokens: int = 1024,
                 temperature: float = 0.3) -> BackendResponse:
        facts_block = _extract_facts_block(prompt)
        critical = [l for l in facts_block if l.startswith('  !')]
        routine = [l for l in facts_block if l.startswith('  -')]

        # Summary: one sentence per system area we have facts about.
        summary_bits: List[str] = []
        categories = _category_bucket(facts_block)
        if 'LATENCY' in categories:
            summary_bits.append(
                f"Latency telemetry captured across {len(categories['LATENCY'])} "
                f"metric(s)."
            )
        if 'RISK' in categories:
            summary_bits.append(
                f"Risk gate emitted {len(categories['RISK'])} observation(s)."
            )
        if 'THROUGHPUT' in categories:
            summary_bits.append("Throughput sampled within expected envelope.")
        if 'ANOMALY' in categories:
            summary_bits.append(
                f"{len(categories['ANOMALY'])} anomaly signal(s) flagged."
            )
        summary = " ".join(summary_bits) or (
            "Trace analysis completed; no critical facts extracted."
        )

        # Key findings: critical facts verbatim, then a capped number of
        # routine ones. Never invent numbers that aren't in the facts.
        findings: List[str] = []
        for line in critical:
            findings.append(line.lstrip(' !').strip())
        for line in routine[: max(0, 8 - len(findings))]:
            findings.append(line.lstrip(' -').strip())
        if not findings:
            findings.append("No notable findings in this trace window.")

        # Root cause: if we have a critical anomaly or risk rejection,
        # name it. Otherwise decline to speculate.
        root_cause: Optional[str] = None
        for line in critical:
            low = line.lower()
            if 'rejected' in low or 'anomaly' in low or 'spike' in low:
                root_cause = line.lstrip(' !').strip()
                break

        # Recommendations: derived from known patterns, not free-form.
        recs: List[str] = []
        joined = "\n".join(facts_block).lower()
        if 'rejected' in joined or 'rate limit' in joined:
            recs.append(
                "Review rate-limiter configuration; increase refill rate "
                "only if downstream throughput headroom is confirmed."
            )
        if 'position' in joined and 'limit' in joined:
            recs.append(
                "Audit position-limit configuration against current inventory "
                "policy; tighten if breaches are sustained."
            )
        if 'tail' in joined or 'p999' in joined or 'p99.9' in joined:
            recs.append(
                "Investigate tail latency: capture a longer trace window and "
                "correlate with upstream bursts or GC-adjacent host activity."
            )
        if 'backpressure' in joined:
            recs.append(
                "Quantify downstream readiness; backpressure at the shell is "
                "usually a consumer-side bottleneck, not an RTL regression."
            )
        if not recs:
            recs.append(
                "No configuration change indicated by this trace. "
                "Re-run analysis if behaviour shifts."
            )

        # Emit in the canonical 4-section shape the parser expects.
        out = [
            "SUMMARY",
            summary,
            "",
            "KEY FINDINGS",
        ]
        out.extend(f"- {f}" for f in findings)
        if root_cause:
            out.extend(["", "ROOT CAUSE", root_cause])
        out.extend(["", "RECOMMENDATIONS"])
        out.extend(f"- {r}" for r in recs)

        return BackendResponse(
            text="\n".join(out),
            backend=self.name,
            model="rules-v1",
            offline=True,
        )


def _extract_facts_block(prompt: str) -> List[str]:
    """Return the lines of the FACTS: block from a generated prompt."""
    lines = prompt.splitlines()
    out: List[str] = []
    in_facts = False
    for line in lines:
        if line.strip().startswith("FACTS:"):
            in_facts = True
            continue
        if in_facts:
            if line.strip() and not line.startswith((' ', '[')) and not line.startswith('  '):
                # Next top-level section — stop.
                break
            out.append(line)
    return out


def _category_bucket(fact_lines: List[str]) -> dict:
    out: dict = {}
    current: Optional[str] = None
    for line in fact_lines:
        m = re.match(r"\[([A-Z]+)\]", line.strip())
        if m:
            current = m.group(1)
            out.setdefault(current, [])
            continue
        if current and line.strip():
            out[current].append(line)
    return out


# ---------------------------------------------------------------------------
# Ollama (local LLM)
# ---------------------------------------------------------------------------

class OllamaBackend(Backend):
    """Call a locally-running Ollama server.

    Designed for prop-desk / compliance-sensitive environments where
    sending cycle-accurate trading traces to a third-party API is a
    non-starter. No traces leave the host.
    """

    name = "ollama"
    offline = True

    def __init__(self, model: str = "llama3.1:8b",
                 host: str = "http://localhost:11434",
                 timeout_s: float = 30.0):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s

    def available(self) -> bool:
        try:
            import urllib.request
            with urllib.request.urlopen(
                f"{self.host}/api/tags", timeout=1.5
            ) as resp:  # noqa: S310 — intentional localhost call
                return resp.status == 200
        except Exception:
            return False

    def generate(self, system: str, prompt: str, *, max_tokens: int = 1024,
                 temperature: float = 0.3) -> BackendResponse:
        import urllib.request
        import urllib.error

        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read())
            return BackendResponse(
                text=payload.get("response", "").strip(),
                backend=self.name,
                model=self.model,
                offline=True,
            )
        except (urllib.error.URLError, TimeoutError) as e:
            raise BackendUnavailable(
                f"ollama unreachable at {self.host}: {e}"
            ) from e


# ---------------------------------------------------------------------------
# Anthropic (network, opt-in only)
# ---------------------------------------------------------------------------

class AnthropicBackend(Backend):
    """Claude API. Disabled unless explicitly selected — routing traces to a
    third-party API is a compliance non-starter for most prop desks."""

    name = "anthropic"
    offline = False

    def __init__(self, model: str = "claude-sonnet-4-20250514",
                 api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def generate(self, system: str, prompt: str, *, max_tokens: int = 1024,
                 temperature: float = 0.3) -> BackendResponse:
        if not self.available():
            raise BackendUnavailable(
                "anthropic backend unavailable: missing package or API key"
            )
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return BackendResponse(
            text=resp.content[0].text,
            backend=self.name,
            model=self.model,
            offline=False,
        )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def make_backend(name: str = "auto", *,
                 ollama_model: Optional[str] = None,
                 ollama_host: Optional[str] = None,
                 anthropic_model: Optional[str] = None,
                 anthropic_api_key: Optional[str] = None) -> Backend:
    """Return a ready-to-use backend.

    ``name`` is one of ``auto``, ``deterministic``, ``none``, ``ollama``,
    ``anthropic``.

    ``auto`` selection order is **deterministic first**: we never reach
    for an LLM unless the operator has either set up a local Ollama
    server (opt-in) or explicitly asked for Anthropic. This protects
    against accidental data egress.
    """
    name = (name or "auto").lower()
    env_override = os.environ.get("SENTINEL_AI_BACKEND")
    if env_override and name == "auto":
        name = env_override.lower()

    if name in ("none", "deterministic", "offline"):
        return DeterministicBackend()

    if name == "ollama":
        backend = OllamaBackend(
            model=ollama_model or os.environ.get("SENTINEL_OLLAMA_MODEL", "llama3.1:8b"),
            host=ollama_host or os.environ.get("SENTINEL_OLLAMA_HOST", "http://localhost:11434"),
        )
        if not backend.available():
            raise BackendUnavailable(
                f"ollama backend requested but server at {backend.host} is unreachable"
            )
        return backend

    if name == "anthropic":
        backend = AnthropicBackend(
            model=anthropic_model or "claude-sonnet-4-20250514",
            api_key=anthropic_api_key,
        )
        if not backend.available():
            raise BackendUnavailable(
                "anthropic backend requested but ANTHROPIC_API_KEY or "
                "anthropic package is missing"
            )
        return backend

    # auto: deterministic is the safe default. An operator opts in to
    # network/local LLMs explicitly.
    return DeterministicBackend()


__all__ = [
    "Backend",
    "BackendResponse",
    "BackendUnavailable",
    "DeterministicBackend",
    "OllamaBackend",
    "AnthropicBackend",
    "make_backend",
]
