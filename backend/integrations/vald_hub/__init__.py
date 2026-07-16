"""VALD Hub integration — client + DTOs + exceptions.

Transport/auth only. The per-club sync (profile matching + test → ExamResult
mapping) lives in `exams/services/vald_sync.py`.
"""
from .client import ValdHubClient
from .dtos import ValdProfile
from .exceptions import (
    ValdAuthError,
    ValdBadResponse,
    ValdError,
    ValdRateLimitError,
    ValdUpstreamError,
)

__all__ = [
    "ValdHubClient",
    "ValdProfile",
    "ValdError",
    "ValdAuthError",
    "ValdRateLimitError",
    "ValdUpstreamError",
    "ValdBadResponse",
]
