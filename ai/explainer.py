"""LLM-based explanation generator."""

from dataclasses import dataclass
from typing import Optional, List
import os

from .prompts import SYSTEM_PROMPT, EXPLANATION_PROMPT, EXECUTIVE_SUMMARY_PROMPT, COMPARISON_PROMPT
from .pattern_detector import PatternDetectionResult
from .fact_extractor import FactSet


@dataclass
class ExplanationConfig:
    """Configuration for explanation generation."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    temperature: float = 0.3
    clock_period_ns: float = 10.0
    rate_max_tokens: int = 100
    rate_refill_rate: int = 10
    pos_max_long: int = 10000
    pos_max_short: int = 10000


@dataclass
class Explanation:
    """Generated explanation."""
    summary: str
    key_findings: List[str]
    root_cause: Optional[str]
    recommendations: List[str]
    raw_response: str

    def to_dict(self) -> dict:
        return {
            'summary': self.summary,
            'key_findings': self.key_findings,
            'root_cause': self.root_cause,
            'recommendations': self.recommendations,
        }

    def to_markdown(self) -> str:
        lines = ["## Analysis Summary", "", self.summary, "", "## Key Findings", ""]
        for finding in self.key_findings:
            lines.append(f"- {finding}")

        if self.root_cause:
            lines.extend(["", "## Root Cause Analysis", "", self.root_cause])

        if self.recommendations:
            lines.extend(["", "## Recommendations", ""])
            for rec in self.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)


class Explainer:
    """Generate natural language explanations from trace analysis."""

    def __init__(self, config: ExplanationConfig = None, api_key: str = None):
        self.config = config or ExplanationConfig()
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required for AI explanations")

    def explain(self, facts: FactSet, patterns: PatternDetectionResult) -> Explanation:
        """Generate explanation from facts and patterns."""
        prompt = EXPLANATION_PROMPT.format(
            facts=facts.to_llm_context(),
            clock_period_ns=self.config.clock_period_ns,
            rate_max_tokens=self.config.rate_max_tokens,
            rate_refill_rate=self.config.rate_refill_rate,
            pos_max_long=self.config.pos_max_long,
            pos_max_short=self.config.pos_max_short,
        )

        response = self._call_llm(prompt)
        return self._parse_explanation(response)

    def executive_summary(self, facts: FactSet) -> str:
        """Generate brief executive summary."""
        prompt = EXECUTIVE_SUMMARY_PROMPT.format(facts=facts.to_llm_context())
        return self._call_llm(prompt)

    def compare_runs(self, baseline: FactSet, candidate: FactSet) -> str:
        """Compare two analysis runs."""
        prompt = COMPARISON_PROMPT.format(
            baseline_facts=baseline.to_llm_context(),
            candidate_facts=candidate.to_llm_context(),
        )
        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM API."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except ImportError:
            return self._fallback_explanation(prompt)
        except Exception as e:
            return f"Error calling LLM: {e}"

    def _fallback_explanation(self, prompt: str) -> str:
        """Fallback when LLM is unavailable."""
        return """AI explanation unavailable (anthropic package not installed).
Install with: pip install anthropic
Set API key: export ANTHROPIC_API_KEY=your_key"""

    def _parse_explanation(self, response: str) -> Explanation:
        """Parse LLM response into structured explanation."""
        summary = ""
        key_findings: List[str] = []
        root_cause: Optional[str] = None
        recommendations: List[str] = []
        current_section: Optional[str] = None

        for line in response.split('\n'):
            line = line.strip()

            if 'SUMMARY' in line.upper():
                current_section = 'summary'
            elif 'KEY FINDINGS' in line.upper() or 'FINDINGS' in line.upper():
                current_section = 'findings'
            elif 'ROOT CAUSE' in line.upper():
                current_section = 'root_cause'
            elif 'RECOMMENDATION' in line.upper():
                current_section = 'recommendations'
            elif line:
                if current_section == 'summary':
                    summary += line + " "
                elif current_section == 'findings':
                    if line.startswith(('- ', '* ', '1.', '2.', '3.', '4.', '5.')):
                        key_findings.append(line.lstrip('-*0123456789. '))
                elif current_section == 'root_cause':
                    root_cause = (root_cause or "") + line + " "
                elif current_section == 'recommendations':
                    if line.startswith(('- ', '* ', '1.', '2.', '3.', '4.', '5.')):
                        recommendations.append(line.lstrip('-*0123456789. '))

        return Explanation(
            summary=summary.strip(),
            key_findings=key_findings,
            root_cause=root_cause.strip() if root_cause else None,
            recommendations=recommendations,
            raw_response=response,
        )
