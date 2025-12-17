"""
Analysis module for Sentinel-HFT.
"""

from .reproducibility import (
    check_reproducibility,
    ComparisonTrust,
    ReproducibilityReport,
    ReproducibilityError,
)
from .minimizer import (
    minimize_reproducer,
    create_regression_checker,
    minimize_from_files,
    save_minimized,
    MinimizedResult,
)

__all__ = [
    'check_reproducibility',
    'ComparisonTrust',
    'ReproducibilityReport',
    'ReproducibilityError',
    'minimize_reproducer',
    'create_regression_checker',
    'minimize_from_files',
    'save_minimized',
    'MinimizedResult',
]
