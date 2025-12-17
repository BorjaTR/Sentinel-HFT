"""
FPGA-specific implementation hints and optimizations.

Provides vendor-specific guidance for:
- Xilinx UltraScale+
- Intel Agilex/Stratix
- Lattice
"""

from .hints import (
    FPGAFamily,
    FPGAHints,
    TimingConstraint,
    ResourceEstimate,
    ImplementationStrategy,
)

__all__ = [
    'FPGAFamily',
    'FPGAHints',
    'TimingConstraint',
    'ResourceEstimate',
    'ImplementationStrategy',
]
