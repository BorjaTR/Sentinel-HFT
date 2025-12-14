"""AI-powered explanation package for Sentinel-HFT.

This package provides AI-enhanced analysis of trace data, transforming
raw metrics into actionable insights.

Key components:
- PatternDetector: Identifies meaningful patterns in trace data
- FactExtractor: Extracts structured facts for LLM consumption
- Explainer: Generates natural language explanations using LLM
- AIReportGenerator: Creates complete analysis reports
"""

from .pattern_detector import (
    PatternType,
    Pattern,
    PatternDetectionResult,
    PatternDetector,
)

from .fact_extractor import (
    Fact,
    FactSet,
    FactExtractor,
)

from .explainer import (
    ExplanationConfig,
    Explanation,
    Explainer,
)

from .report_generator import (
    AIReport,
    AIReportGenerator,
)

__all__ = [
    # Pattern detection
    'PatternType',
    'Pattern',
    'PatternDetectionResult',
    'PatternDetector',
    # Fact extraction
    'Fact',
    'FactSet',
    'FactExtractor',
    # Explanation
    'ExplanationConfig',
    'Explanation',
    'Explainer',
    # Report generation
    'AIReport',
    'AIReportGenerator',
]
