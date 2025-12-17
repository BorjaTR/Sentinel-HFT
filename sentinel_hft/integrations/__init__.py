"""
Integrations module for Sentinel-HFT.
"""

from .github_pr import (
    generate_pr_comment,
    generate_comment_identifier,
    wrap_with_identifier,
    PRCommentData,
)

__all__ = [
    'generate_pr_comment',
    'generate_comment_identifier',
    'wrap_with_identifier',
    'PRCommentData',
]
