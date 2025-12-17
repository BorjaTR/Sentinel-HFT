"""
FixPack template system for Sentinel-HFT.

Provides parameterized RTL templates for common HFT latency patterns.
"""

from .schema import (
    FPGAVendor,
    ResourceType,
    FPGAResources,
    TemplateParameter,
    TemplateMetadata,
)
from .generator import FixPackGenerator

__all__ = [
    'FPGAVendor',
    'ResourceType',
    'FPGAResources',
    'TemplateParameter',
    'TemplateMetadata',
    'FixPackGenerator',
]
