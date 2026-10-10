"""Strict, offline-only R2V2-B4_LLM routing harness."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from evaluation.capability_routing_rq2_v2_stage0 import CAPABILITY_FIELDS
from evaluation.capability_routing_rq2_v2_stage0.interfaces import RouterPrediction

from .mock_provider import DeterministicMockProvider


PACKAGE_ROOT = Path(__file__).resolve().parent
PROMPT_TEMPLATE_PATH = PACKAGE_ROOT / "prompt_template.txt"

PRIMARY_SEMANTIC_INPUT_PROFILE = "R2V2_PRIMARY_SEMANTIC_INPUT_V1"
PRIMARY_SEMANTIC_INPUT_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
STAGE0_COMPATIBILITY_ONLY_FIELDS = frozenset(
    {"rag_context_state", "memory_context_state"}
)
CURRENT_PAGES = {"Overview", "Resources", "Lecture", "Debate", "Reflection", "Other"}
FEW_SHOT_PLACEHOLDER = (
    "[PLACEHOLDER ONLY: final examples are not selected. A later authorised stage "
    "may insert development-only examples before final-test access.]"
)
_REASON_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")


class PromptInputError(ValueError):
    """Raised when input is not exactly the canonical model-visible object."""


class B4ResponseParseError(ValueError):
    """Clear fail-closed parser error for an invalid B4 response."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class OfflineProviderRequiredError(RuntimeError):
    """Raised if a provider does not attest and retain offline-only state."""


class ProviderAccountingError(RuntimeError):
    """Raised if one B4 route is not accounted as exactly one mock call."""


class OfflineTextProvider(Protocol):
    """Minimal provider boundary; Stage 1D implements only the mock provider."""

    offline_only: bool
    provider_name: str

    @property
    def call_count(self) -> int: ...

    @property
    def network_call_count(self) -> int: ...

    @property
    def real_provider_call_count(self) -> int: ...

    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class B4CapabilityResponse:
    rag_required: bool
    memory_required: bool
    planning_required: bool
    reason_code: str | None = None

    def capabilities(self) -> dict[str, bool]:
        return {
            "rag_required": self.rag_required,
            "memory_required": self.memory_required,
            "planning_required": self.planning_required,
        }


def _field_error(prefix: str, fields: set[Any]) -> str:
    return f"{prefix}: {', '.join(sorted(repr(field) for field in fields))}"


def extract_primary_semantic_input(model_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the four fields in R2V2_PRIMARY_SEMANTIC_INPUT_V1.

    A Stage 0-compatible mapping may also carry the two context-state fields.
    They are tolerated for schema compatibility but neither accessed nor copied.
    """

    if not isinstance(model_input, Mapping):
        raise PromptInputError("model_input must be a mapping")
    expected = set(PRIMARY_SEMANTIC_INPUT_FIELDS)
    allowed = expected | STAGE0_COMPATIBILITY_ONLY_FIELDS
    observed = set(model_input)
    missing = expected - observed
    unknown = observed - allowed
    if missing:
        raise PromptInputError(_field_error("missing primary semantic fields", missing))
    if unknown:
        raise PromptInputError(_field_error("unknown or hidden input fields", unknown))

    current_query = model_input["current_query"]
    if not isinstance(current_query, str) or not current_query.strip():
        raise PromptInputError("current_query must be a non-empty string")
    current_page = model_input["current_page"]
    if current_page not in CURRENT_PAGES:
        raise PromptInputError("current_page is outside the canonical page enum")
    dashboard_context = model_input["dashboard_context"]
    if not isinstance(dashboard_context, str):
        raise PromptInputError("dashboard_context must be a string")

    raw_history = model_input["visible_conversation_history"]
    if not isinstance(raw_history, list):
        raise PromptInputError("visible_conversation_history must be a JSON-style list")
    history: list[dict[str, str]] = []
    for index, turn in enumerate(raw_history):
        if not isinstance(turn, Mapping) or set(turn) != {"role", "content"}:
            raise PromptInputError(
                f"visible_conversation_history[{index}] must contain only role and content"
            )
        role = turn["role"]
        content = turn["content"]
        if role not in {"user", "assistant"}:
            raise PromptInputError(
                f"visible_conversation_history[{index}].role is invalid"
            )
        if not isinstance(content, str) or not content:
            raise PromptInputError(
                f"visible_conversation_history[{index}].content must be non-empty"
            )
        history.append({"role": role, "content": content})

    return {
        "current_query": current_query,
        "current_page": current_page,
        "dashboard_context": dashboard_context,
        "visible_conversation_history": history,
    }


def build_b4_prompt(model_input: Mapping[str, Any]) -> str:
    """Render B4 from the four-field primary semantic profile only."""

    visible = extract_primary_semantic_input(model_input)
    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{FEW_SHOT_EXAMPLES}}": FEW_SHOT_PLACEHOLDER,
        "{{CURRENT_QUERY_JSON}}": json.dumps(visible["current_query"], ensure_ascii=False),
        "{{CURRENT_PAGE_JSON}}": json.dumps(visible["current_page"], ensure_ascii=False),
        "{{DASHBOARD_CONTEXT_JSON}}": json.dumps(
            visible["dashboard_context"], ensure_ascii=False
        ),
        "{{VISIBLE_HISTORY_JSON}}": json.dumps(
            visible["visible_conversation_history"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    rendered = template
    for token, value in replacements.items():
        if token not in rendered:
            raise PromptInputError(f"prompt template token is missing: {token}")
        rendered = rendered.replace(token, value)
    if "{{" in rendered or "}}" in rendered:
        raise PromptInputError("prompt template contains an unresolved token")
    return rendered


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise B4ResponseParseError(
                "DUPLICATE_FIELD", f"response contains duplicate field {key!r}"
            )
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise B4ResponseParseError(
        "INVALID_JSON_CONSTANT", f"non-JSON numeric constant is forbidden: {value}"
    )


def parse_b4_response(raw_response: str) -> B4CapabilityResponse:
    """Parse one exact JSON object, rejecting prose, guessing, and type coercion."""

    if not isinstance(raw_response, str):
        raise B4ResponseParseError("RESPONSE_NOT_TEXT", "provider response must be text")
    candidate = raw_response.strip()
    if not candidate:
        raise B4ResponseParseError("EMPTY_RESPONSE", "provider response is empty")

    decoder = json.JSONDecoder(
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_json_constant,
    )
    try:
        value, end = decoder.raw_decode(candidate)
    except B4ResponseParseError:
        raise
    except json.JSONDecodeError as exc:
        raise B4ResponseParseError(
            "INVALID_JSON", f"JSON decoding failed at character {exc.pos}"
        ) from exc
    if candidate[end:].strip():
        raise B4ResponseParseError(
            "EXTRA_TEXT", "non-whitespace text follows the JSON object"
        )
    if not isinstance(value, dict):
        raise B4ResponseParseError("RESPONSE_NOT_OBJECT", "response must be a JSON object")

    required = set(CAPABILITY_FIELDS)
    allowed = required | {"reason_code"}
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise B4ResponseParseError(
            "MISSING_REQUIRED_FIELD", _field_error("missing fields", missing)
        )
    if unknown:
        raise B4ResponseParseError(
            "UNKNOWN_RESPONSE_FIELD", _field_error("unknown fields", unknown)
        )
    for field in CAPABILITY_FIELDS:
        if type(value[field]) is not bool:
            raise B4ResponseParseError(
                "INVALID_BOOLEAN_TYPE", f"{field} must be a JSON boolean"
            )

    reason_code = value.get("reason_code")
    if reason_code is not None and (
        not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code)
    ):
        raise B4ResponseParseError(
            "INVALID_REASON_CODE",
            "reason_code must be a 1-64 character code without spaces",
        )
    return B4CapabilityResponse(
        rag_required=value["rag_required"],
        memory_required=value["memory_required"],
        planning_required=value["planning_required"],
        reason_code=reason_code,
    )


class B4OfflineHarness:
    """One-call offline B4 adapter over an explicitly offline provider."""

    model_id = "R2V2-B4_LLM"

    def __init__(self, provider: OfflineTextProvider) -> None:
        if not isinstance(provider, DeterministicMockProvider):
            raise OfflineProviderRequiredError(
                "R2V2-B4 Stage 1D accepts only DeterministicMockProvider"
            )
        if getattr(provider, "offline_only", False) is not True:
            raise OfflineProviderRequiredError(
                "R2V2-B4 Stage 1D requires an offline-only provider"
            )
        self._provider = provider
        self._assert_zero_external_calls()

    @property
    def provider_call_count(self) -> int:
        return int(self._provider.call_count)

    def _assert_zero_external_calls(self) -> None:
        network_calls = int(self._provider.network_call_count)
        real_calls = int(self._provider.real_provider_call_count)
        if network_calls != 0 or real_calls != 0:
            raise OfflineProviderRequiredError(
                "offline provider reports network or real-provider activity"
            )

    def predict(
        self, *, case_id: str, model_input: Mapping[str, Any]
    ) -> RouterPrediction:
        if not isinstance(case_id, str) or not case_id:
            raise PromptInputError("case_id must be a non-empty diagnostic identifier")
        prompt = build_b4_prompt(model_input)
        self._assert_zero_external_calls()
        before = self.provider_call_count
        raw_response = self._provider.complete(prompt)
        after = self.provider_call_count
        if after - before != 1:
            raise ProviderAccountingError(
                "one B4 prediction must increment the provider call counter exactly once"
            )
        self._assert_zero_external_calls()
        parsed = parse_b4_response(raw_response)
        return RouterPrediction(
            case_id=case_id,
            model_id=self.model_id,
            dialogue_action="ANSWER",
            metadata={
                "execution_mode": "OFFLINE_DETERMINISTIC_MOCK",
                "provider_name": str(self._provider.provider_name),
                "provider_call_count": after - before,
                "provider_total_call_count": after,
                "real_provider_call_count": 0,
                "network_access": False,
                "training_performed": False,
                "final_prediction_source": self.model_id,
                "input_profile": PRIMARY_SEMANTIC_INPUT_PROFILE,
                "reason_code": parsed.reason_code,
                "token_count": None,
                "estimated_cost": None,
                "latency": None,
            },
            **parsed.capabilities(),
        )
