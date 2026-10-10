"""Explicit, fail-closed errors for the Stage 1 Track C research code."""

from __future__ import annotations


class TrackCError(RuntimeError):
    """Base error for the isolated B2/B3 implementation."""


class CanonicalInputError(TrackCError, ValueError):
    """A case does not provide valid canonical model-visible input."""


class EmbeddingAdapterError(TrackCError):
    """The frozen local encoder or its output violates the adapter contract."""


class DevelopmentDataError(TrackCError, ValueError):
    """Development-only data is missing, malformed, or ineligible."""


class DegenerateLabelError(DevelopmentDataError):
    """A capability has no positive or no negative development examples."""


class ModelStateError(TrackCError, ValueError):
    """A fitted B2/B3 state is missing, malformed, or incompatible."""
