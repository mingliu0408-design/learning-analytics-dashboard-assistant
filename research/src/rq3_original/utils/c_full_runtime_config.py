"""Validated live C_FULL retrieval configuration without importing Streamlit."""

from __future__ import annotations

import os
from typing import Any, Mapping


ALLOWED_C_FULL_RETRIEVAL_BACKENDS = {"v1", "v2_4"}


def _configured_value(
    name: str,
    *,
    secrets: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None,
) -> Any:
    if secrets is not None:
        try:
            if name in secrets:
                return secrets[name]
        except Exception:
            pass
    environment = os.environ if environ is None else environ
    return environment.get(name)


def get_streamlit_retrieval_backend(
    *,
    secrets: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve secret, environment, then safe live default (v2_4)."""

    raw = _configured_value(
        "C_FULL_RETRIEVAL_BACKEND", secrets=secrets, environ=environ
    )
    backend = str(raw if raw is not None else "v2_4").strip().casefold()
    if backend not in ALLOWED_C_FULL_RETRIEVAL_BACKENDS:
        allowed = ", ".join(sorted(ALLOWED_C_FULL_RETRIEVAL_BACKENDS))
        raise ValueError(
            f"Invalid C_FULL_RETRIEVAL_BACKEND={raw!r}. Allowed values: {allowed}."
        )
    return backend


def get_streamlit_allow_retrieval_v1_fallback(
    *,
    secrets: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return the explicit fallback setting; false is the safe default."""

    raw = _configured_value(
        "C_FULL_ALLOW_RETRIEVAL_V1_FALLBACK", secrets=secrets, environ=environ
    )
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    normalised = str(raw).strip().casefold()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        "Invalid C_FULL_ALLOW_RETRIEVAL_V1_FALLBACK value; use true or false."
    )


def get_streamlit_retrieval_debug(
    *,
    secrets: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    raw = _configured_value(
        "C_FULL_RETRIEVAL_DEBUG", secrets=secrets, environ=environ
    )
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    normalised = str(raw).strip().casefold()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Invalid C_FULL_RETRIEVAL_DEBUG value; use true or false.")
