"""
Prescription engine for Sentinel-HFT.
"""

from .multi_detector import (
    MultiPatternDetector,
    PatternMatch,
    DetectionResult,
    ConfidenceLevel,
    EvidenceItem,
)

__all__ = [
    'MultiPatternDetector',
    'PatternMatch',
    'DetectionResult',
    'ConfidenceLevel',
    'EvidenceItem',
]
