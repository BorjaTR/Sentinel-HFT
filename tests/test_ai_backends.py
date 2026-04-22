"""Tests for pluggable AI backends.

Covers:
- Deterministic backend always available, produces well-formed output
- Ollama backend correctly detects unavailability and can be mocked
- Anthropic backend refuses to run without a key
- ``make_backend`` selector resolves auto/deterministic/none safely
- ``Explainer`` falls back to deterministic rather than raising
- No backend performs network calls when the default is used
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.backends import (  # noqa: E402
    AnthropicBackend,
    Backend,
    BackendResponse,
    BackendUnavailable,
    DeterministicBackend,
    OllamaBackend,
    make_backend,
)
from ai.explainer import Explainer, ExplanationConfig  # noqa: E402
from ai.fact_extractor import Fact, FactSet  # noqa: E402
from ai.prompts import EXPLANATION_PROMPT, SYSTEM_PROMPT  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_facts() -> FactSet:
    """A FactSet with one of each category including a critical fact."""
    fs = FactSet()
    fs.add(Fact(category='latency', key='p99',
                value=450,
                context='P99 latency at 450 cycles (4.5 microseconds)',
                importance='medium'))
    fs.add(Fact(category='risk', key='rejected_rate',
                value=12,
                context='12 orders rejected by rate limiter in window',
                importance='high'))
    fs.add(Fact(category='anomaly', key='tail_spike',
                value=True,
                context='Tail spike detected at seq 18432',
                importance='critical'))
    fs.add(Fact(category='throughput', key='tps',
                value=48000,
                context='Sustained 48000 tx/sec',
                importance='low'))
    return fs


@pytest.fixture
def sample_prompt(sample_facts: FactSet) -> str:
    return EXPLANATION_PROMPT.format(
        facts=sample_facts.to_llm_context(),
        clock_period_ns=10.0,
        rate_max_tokens=100,
        rate_refill_rate=10,
        pos_max_long=10000,
        pos_max_short=10000,
    )


# ---------------------------------------------------------------------------
# DeterministicBackend
# ---------------------------------------------------------------------------

class TestDeterministicBackend:

    def test_always_available(self):
        assert DeterministicBackend().available() is True

    def test_response_is_offline_and_well_formed(self, sample_prompt: str):
        resp = DeterministicBackend().generate(SYSTEM_PROMPT, sample_prompt)
        assert isinstance(resp, BackendResponse)
        assert resp.offline is True
        assert resp.backend == 'deterministic'
        text = resp.text
        # Canonical sections must appear in order.
        assert 'SUMMARY' in text
        assert 'KEY FINDINGS' in text
        assert 'RECOMMENDATIONS' in text

    def test_surfaces_critical_facts(self, sample_prompt: str):
        resp = DeterministicBackend().generate(SYSTEM_PROMPT, sample_prompt)
        # Critical anomaly should be called out somewhere.
        assert 'Tail spike' in resp.text

    def test_does_not_invent_numbers(self, sample_prompt: str):
        """Rule-based output must not contain numbers that aren't in the
        facts. Protects against hallucinated latency values leaking into
        DORA audit evidence."""
        resp = DeterministicBackend().generate(SYSTEM_PROMPT, sample_prompt)
        # Known facts have numbers 450, 12, 18432, 48000 — any other 3+
        # digit number is suspicious.
        import re
        allowed = {'450', '12', '18432', '48000', '10', '100', '10000'}
        candidates = re.findall(r'\b\d{3,}\b', resp.text)
        for n in candidates:
            assert n in allowed, (
                f"deterministic backend emitted unknown number {n}; "
                f"it should only reference facts it was given"
            )

    def test_empty_facts_still_produce_output(self):
        empty = FactSet()
        prompt = EXPLANATION_PROMPT.format(
            facts=empty.to_llm_context(),
            clock_period_ns=10.0, rate_max_tokens=100, rate_refill_rate=10,
            pos_max_long=1, pos_max_short=1,
        )
        resp = DeterministicBackend().generate(SYSTEM_PROMPT, prompt)
        # Does not raise, still well-formed.
        assert 'SUMMARY' in resp.text


# ---------------------------------------------------------------------------
# OllamaBackend
# ---------------------------------------------------------------------------

class TestOllamaBackend:

    def test_unavailable_when_server_missing(self):
        """Default host is localhost:11434; if unreachable we report
        unavailable cleanly instead of crashing."""
        backend = OllamaBackend(host="http://127.0.0.1:1")  # port 1 never listens
        assert backend.available() is False

    def test_generate_raises_when_unreachable(self, sample_prompt: str):
        backend = OllamaBackend(host="http://127.0.0.1:1", timeout_s=0.5)
        with pytest.raises(BackendUnavailable):
            backend.generate(SYSTEM_PROMPT, sample_prompt)

    def test_generate_parses_response(self, sample_prompt: str):
        """Mock the HTTP call and verify response shaping."""
        import urllib.request

        class FakeResp:
            status = 200
            def read(self):
                return json.dumps({"response": "SUMMARY\nOK\n"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        backend = OllamaBackend(model="test-model")
        with patch.object(urllib.request, 'urlopen', return_value=FakeResp()):
            resp = backend.generate(SYSTEM_PROMPT, sample_prompt)
        assert resp.backend == 'ollama'
        assert resp.model == 'test-model'
        assert resp.offline is True
        assert 'OK' in resp.text


# ---------------------------------------------------------------------------
# AnthropicBackend
# ---------------------------------------------------------------------------

class TestAnthropicBackend:

    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        backend = AnthropicBackend(api_key=None)
        assert backend.available() is False

    def test_generate_raises_without_key(self, monkeypatch, sample_prompt: str):
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        backend = AnthropicBackend(api_key=None)
        with pytest.raises(BackendUnavailable):
            backend.generate(SYSTEM_PROMPT, sample_prompt)


# ---------------------------------------------------------------------------
# make_backend selector
# ---------------------------------------------------------------------------

class TestMakeBackend:

    def test_auto_returns_deterministic_by_default(self, monkeypatch):
        monkeypatch.delenv('SENTINEL_AI_BACKEND', raising=False)
        b = make_backend('auto')
        assert isinstance(b, DeterministicBackend)

    def test_none_returns_deterministic(self):
        assert isinstance(make_backend('none'), DeterministicBackend)
        assert isinstance(make_backend('deterministic'), DeterministicBackend)
        assert isinstance(make_backend('offline'), DeterministicBackend)

    def test_ollama_requested_but_unavailable_raises(self):
        with pytest.raises(BackendUnavailable):
            make_backend('ollama', ollama_host='http://127.0.0.1:1')

    def test_anthropic_requested_but_unavailable_raises(self, monkeypatch):
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        with pytest.raises(BackendUnavailable):
            make_backend('anthropic', anthropic_api_key=None)

    def test_env_override_respected(self, monkeypatch):
        monkeypatch.setenv('SENTINEL_AI_BACKEND', 'deterministic')
        b = make_backend('auto')
        assert isinstance(b, DeterministicBackend)


# ---------------------------------------------------------------------------
# Explainer integration
# ---------------------------------------------------------------------------

class TestExplainerIntegration:

    def test_default_explainer_works_offline(self, monkeypatch, sample_facts: FactSet):
        """This is the critical regression: an Explainer built with no
        config and no API key must not fail, must not call the network,
        and must produce a structured Explanation."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.delenv('SENTINEL_AI_BACKEND', raising=False)

        explainer = Explainer()
        assert explainer.backend_name == 'deterministic'
        assert explainer.offline is True

        out = explainer.explain(sample_facts)
        assert out.backend == 'deterministic'
        assert out.offline is True
        assert out.summary  # non-empty
        assert len(out.key_findings) >= 1

    def test_markdown_includes_backend_footer(self, sample_facts: FactSet):
        explainer = Explainer()
        out = explainer.explain(sample_facts)
        md = out.to_markdown()
        assert 'deterministic' in md
        assert 'offline' in md

    def test_explainer_falls_back_when_ollama_requested_but_absent(
        self, monkeypatch, sample_facts: FactSet
    ):
        """If the operator asks for ollama but the server is down, we
        must fall back to deterministic rather than crash. The test
        ensures graceful degradation in a demo setting."""
        monkeypatch.delenv('SENTINEL_AI_BACKEND', raising=False)
        cfg = ExplanationConfig(
            backend='ollama',
            ollama_host='http://127.0.0.1:1',  # dead
        )
        explainer = Explainer(config=cfg)
        # Resolved backend should be deterministic after fallback.
        assert explainer.backend_name == 'deterministic'
        out = explainer.explain(sample_facts)
        assert out.offline is True

    def test_to_dict_includes_provenance(self, sample_facts: FactSet):
        explainer = Explainer()
        d = explainer.explain(sample_facts).to_dict()
        assert 'backend' in d
        assert 'offline' in d
        assert d['offline'] is True

    def test_no_network_call_in_default_path(self, monkeypatch, sample_facts: FactSet):
        """Smoke test: patch urllib.request.urlopen to blow up; default
        Explainer must still succeed (proves we didn't accidentally
        introduce a hidden HTTP call in the default path)."""
        import urllib.request
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        monkeypatch.delenv('SENTINEL_AI_BACKEND', raising=False)

        def _boom(*a, **k):  # pragma: no cover - fires on failure only
            raise AssertionError("default path made a network call")

        monkeypatch.setattr(urllib.request, 'urlopen', _boom)
        explainer = Explainer()
        out = explainer.explain(sample_facts)
        assert out.offline is True
        assert out.backend == 'deterministic'
