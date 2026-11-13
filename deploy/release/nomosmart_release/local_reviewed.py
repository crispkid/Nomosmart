"""Explicit entry point; never infer risk-reviewed purpose from a candidate."""
from .local_verified import _assemble_local_release

def assemble_local_reviewed_release(**kwargs):
    return _assemble_local_release(**kwargs, reviewed=True)
