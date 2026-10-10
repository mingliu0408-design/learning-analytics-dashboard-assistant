"""Conservative production adapter for C_FULL intent selection.

The adapter keeps the existing deterministic classifier authoritative in
``keyword_baseline`` mode and as the safe fallback in ``semantic_enhanced``
mode.  It consumes the frozen semantic router API; it does not duplicate
embedding or similarity logic and never changes source scope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from utils.dashboard_domain_resolver import (
    detect_explicit_dashboard_domains,
    is_explicit_whole_dashboard_query,
)
from utils.evidence_synthesiser import classify_query_detailed
from utils.intent_schema import FUTURE_SCOPE_OUTCOMES, LEGACY_QUERY_TYPES
from utils.semantic_intent_router import (
    PrecomputedIndexEmbeddingStore,
    SemanticIntentRouter,
    SentenceTransformerEmbeddingBackend,
)


KEYWORD_BASELINE = "keyword_baseline"
SEMANTIC_ENHANCED = "semantic_enhanced"
ALLOWED_ROUTING_MODES = (KEYWORD_BASELINE, SEMANTIC_ENHANCED)
ROUTER_MODE_ENVIRONMENT_VARIABLE = "DUTEAI_INTENT_ROUTER_MODE"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "semantic_runtime" / "config" / "semantic_routing_config.json"
)

_AUTOMATIC_GUARD_INTENTS = {
    "memory_state_query": "memory_state_guard",
    "access_or_capability_question": "capability_guard",
    "discrepancy_or_correction": "correction_guard",
    # The legacy helper is a high-precision definition request.  Allowing a
    # semantic neighbour such as emotional/justification to replace it breaks
    # the original reflection-metric contract.
    "metric_clarification": "metric_definition_guard",
}


def _is_pure_social_interaction(query: str) -> bool:
    """Recognise bounded conversational speech acts, not one literal greeting.

    This guard exists only in semantic-enhanced production handling. It covers
    greeting, gratitude, wellbeing, and farewell utterances while refusing
    messages that also contain a substantive dashboard/course request.
    """

    q = re.sub(r"\s+", " ", str(query or "").casefold()).strip(" .,!?")
    if not q or len(q.split()) > 12:
        return False
    substantive = re.search(
        r"\b(?:dashboard|resource|lecture|video|debate|reflection|course|reading|"
        r"week\s*\d+|w\d+|metric|views?|posts?|replies|plan|strategy|improve)\b",
        q,
    )
    if substantive:
        return False
    return bool(
        re.fullmatch(
            r"(?:hi|hello|hey|morning|good (?:morning|afternoon|evening)|"
            r"how(?:'s| is) it going|how are you|hope you(?:'re| are) well|"
            r"thanks?|thank you|many thanks|cheers|much appreciated|"
            r"i appreciate (?:that|the help|your help)|"
            r"(?:nice|great|brilliant|cheers),? that (?:helps?|cleared things up)|"
            r"good to see you|hey,? good to see you|hello,? hope you(?:'re| are) well|"
            r"good (?:morning|afternoon|evening) to you|"
            r"bye|goodbye|see you(?: later)?|catch you later)"
            r"(?:[!. ]*)",
            q,
        )
    )


@dataclass(frozen=True)
class ProductionIntentDecision:
    """Privacy-safe intent decision metadata; it deliberately stores no query."""

    routing_mode: str
    keyword_intent: str
    keyword_rule_id: str
    semantic_status: str
    semantic_candidate: str | None
    semantic_score: float | None
    semantic_margin: float | None
    semantic_accepted: bool
    selected_intent: str
    routing_source: str
    fallback_reason: str
    protected_guard_reasons: tuple[str, ...]
    uncertainty_fallback_used: bool = False
    uncertainty_reason: str = ""
    clarification_hint_intent: str | None = None
    clarification_hint_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["protected_guard_reasons"] = list(self.protected_guard_reasons)
        return payload


def _normalise_guard_reasons(values: Sequence[str]) -> tuple[str, ...]:
    reasons: list[str] = []
    for value in values:
        reason = re.sub(r"[^a-z0-9_:-]+", "_", str(value).strip().casefold())
        if reason and reason not in reasons:
            reasons.append(reason)
    return tuple(reasons)


def _uncertainty_hint(
    candidate: str | None,
    score: float | None,
) -> tuple[str | None, float | None]:
    """Return a coarse, phrasing-only hint for an uncertainty clarification.

    The hint is deliberately not a routing decision.  It uses only the
    rejected semantic result, never page state, evidence, retrieval, or memory.
    """

    if candidate is None or score is None:
        return None, None
    hint_groups = {
        "planning_or_strategy": "planning_or_strategy",
        "improvement_recommendation": "improvement_recommendation",
        "course_content_question": "course_content_question",
        "course_location_or_access": "course_content_question",
        "hybrid_course_and_planning": "course_content_question",
        "quantitative_metric_query": "dashboard_metric_or_activity",
        "metric_clarification": "dashboard_metric_or_activity",
        "dashboard_interpretation": "dashboard_metric_or_activity",
        "technical_data_question": "dashboard_metric_or_activity",
        "cross_page_relationship": "dashboard_metric_or_activity",
    }
    hint = hint_groups.get(str(candidate))
    return (hint, float(score)) if hint else (None, None)


def _uncertain_decision(
    *,
    routing_mode: str,
    keyword: Any,
    semantic_status: str,
    candidate: str | None,
    score: float | None,
    margin: float | None,
    reason: str,
    guards: tuple[str, ...],
    uncertainty_basis: str = "unmatched_default",
) -> ProductionIntentDecision:
    hint, hint_score = _uncertainty_hint(candidate, score)
    return ProductionIntentDecision(
        routing_mode=routing_mode,
        keyword_intent=keyword.legacy_query_type,
        keyword_rule_id=keyword.rule_id,
        semantic_status=semantic_status,
        semantic_candidate=candidate,
        semantic_score=score,
        semantic_margin=margin,
        semantic_accepted=False,
        selected_intent="semantic_uncertain",
        routing_source="uncertainty_fallback",
        fallback_reason=reason,
        protected_guard_reasons=guards,
        uncertainty_fallback_used=True,
        uncertainty_reason=f"{uncertainty_basis}:{reason}",
        clarification_hint_intent=hint,
        clarification_hint_score=hint_score,
    )


def _has_strong_technical_data_signal(query: str) -> bool:
    """Distinguish real provenance/data-quality requests from a weak cue.

    ``TECHNICAL_DATA_PATTERN`` intentionally remains broad in the historical
    classifier.  Semantic-enhanced conflict handling treats that rule as
    reliable only when the query contains a concrete provenance, calculation,
    schema, quality, or data-operation signal; words such as ``recorded`` or
    ``tracked`` alone are not enough to make the heuristic authoritative.
    """

    q = re.sub(r"\s+", " ", str(query or "").casefold()).strip()
    return bool(
        re.search(
            r"\b(?:data|data source|source|logs?|calculated|calculation|measured|measurement|"
            r"collected|collection|missing data|no data|download|export|columns?|tables?|rows?|"
            r"accurate|accuracy|reliable|reliability|correct|incorrect|valid|validity|"
            r"trust|trustworthy|exact|wrong|errors?)\b",
            q,
        )
    )


def _has_course_lookup_signal(query: str) -> bool:
    """Protect concrete course-material lookup language from relation-word noise."""

    q = re.sub(r"\s+", " ", str(query or "").casefold()).strip()
    return bool(
        re.search(r"\b(?:locate|find|show|open|where|give me)\b", q)
        and re.search(
            r"\b(?:course|teaching|indexed) materials?|\b(?:reading|lecture material)\b",
            q,
        )
    )


def _explicit_heuristic_conflict_reason(
    *,
    keyword: Any,
    query: str,
    result: Any,
) -> str:
    """Return a narrow reason when an explicit intent heuristic is unsafe.

    This never covers authoritative guards.  It applies only after the frozen
    semantic policy has rejected the result and only to two known broad lexical
    intent heuristics whose downstream routes can confidently answer the wrong
    task.  Genuine rule-specific evidence keeps the keyword fallback intact.
    """

    if getattr(result, "status", "") != "available":
        return ""
    candidate = str(getattr(result, "winning_label", "") or "")
    margin = getattr(result, "margin", None)

    if keyword.rule_id == "CROSS_PAGE_RELATIONSHIP_PATTERN":
        domains = detect_explicit_dashboard_domains(query)
        genuine_comparison_scope = len(domains) >= 2 or is_explicit_whole_dashboard_query(query)
        if (
            not genuine_comparison_scope
            and not _has_course_lookup_signal(query)
            and candidate != keyword.legacy_query_type
        ):
            return "cross_page_rule_without_comparison_scope"

    if keyword.rule_id == "TECHNICAL_DATA_PATTERN":
        if _has_strong_technical_data_signal(query):
            return ""
        second_label = str(getattr(result, "second_label", "") or "")
        semantic_conflict = candidate != keyword.legacy_query_type or (
            candidate == keyword.legacy_query_type
            and second_label == "dashboard_interpretation"
            and margin is not None
            and float(margin) < 0.190380
        )
        if semantic_conflict:
            return "technical_rule_without_concrete_data_question"
    return ""


def resolve_intent_router_mode(
    explicit_mode: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve explicit mode, environment, then the integrated-project default."""

    environment = os.environ if environ is None else environ
    raw = explicit_mode
    if raw is None:
        raw = environment.get(ROUTER_MODE_ENVIRONMENT_VARIABLE, SEMANTIC_ENHANCED)
    mode = str(raw).strip().casefold()
    if mode not in ALLOWED_ROUTING_MODES:
        allowed = ", ".join(ALLOWED_ROUTING_MODES)
        raise ValueError(f"Invalid intent router mode {raw!r}; expected one of: {allowed}")
    return mode


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a JSON object: {path}")
    return value


def _project_path(value: str) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _verify_file(path: Path, expected_sha256: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError(f"Frozen semantic artifact SHA-256 mismatch: {path.name}")


def _validated_config(config_path: Path) -> dict[str, Any]:
    config = _load_json_object(config_path)
    if config.get("schema_version") != "duteai-production-intent-routing-v1":
        raise ValueError("Unsupported semantic routing configuration schema")
    if tuple(config.get("allowed_modes") or ()) != ALLOWED_ROUTING_MODES:
        raise ValueError("Semantic routing configuration mode contract changed")
    if config.get("default_mode") != SEMANTIC_ENHANCED:
        raise ValueError("Integrated project must default to semantic_enhanced")
    if config.get("allow_network_downloads") is not False:
        raise ValueError("Semantic runtime must remain local-only")
    if config.get("aggregation") != "max":
        raise ValueError("Frozen semantic aggregation must remain max")
    if config.get("aggregate_all_examples") is not True:
        raise ValueError("Frozen semantic retrieval must aggregate all examples")
    if int(config.get("per_intent_family_limit", 0)) != 3:
        raise ValueError("Frozen per-intent family limit must remain 3")
    for name, expected in {
        "semantic_score_threshold": 0.513765,
        "semantic_margin_threshold": 0.190380,
        "oos_score_threshold": 0.323827,
        "oos_margin_threshold": 0.134525,
    }.items():
        if float(config.get(name, -1.0)) != expected:
            raise ValueError(f"Frozen threshold changed: {name}")

    artifacts = config.get("artifacts") or {}
    approved = artifacts.get("approved_index") or {}
    embeddings = artifacts.get("embedding_npz") or {}
    _verify_file(_project_path(approved["path"]), str(approved["sha256"]))
    _verify_file(_project_path(embeddings["path"]), str(embeddings["sha256"]))
    for required_path in (
        approved["sha256_path"],
        approved["metadata_path"],
        embeddings["sha256_path"],
    ):
        if not _project_path(required_path).is_file():
            raise FileNotFoundError(_project_path(required_path))

    model = config.get("model") or {}
    if model.get("repo_id") != "sentence-transformers/all-mpnet-base-v2":
        raise ValueError("Frozen semantic model repository changed")
    if model.get("revision") != "e8c3b32edf5434bc2275fc9bab85f82640a19130":
        raise ValueError("Frozen semantic model revision changed")
    model_path = _project_path(model["local_path"])
    if not model_path.is_dir() or model_path.name != model["revision"]:
        raise FileNotFoundError(model_path)
    if model.get("local_files_only") is not True:
        raise ValueError("Semantic model loading must remain local-only")
    return config


@lru_cache(maxsize=2)
def _load_validated_config_cached(config_path: str) -> dict[str, Any]:
    """Validate immutable configuration and artifact hashes once per process."""

    return _validated_config(Path(config_path))


@lru_cache(maxsize=2)
def load_production_semantic_router(
    config_path: str = str(DEFAULT_CONFIG_PATH),
) -> SemanticIntentRouter:
    """Build and process-cache the exact local semantic runtime."""

    config_path = str(Path(config_path).resolve())
    config = _load_validated_config_cached(config_path)
    approved = config["artifacts"]["approved_index"]
    embeddings = config["artifacts"]["embedding_npz"]
    model = config["model"]
    backend = SentenceTransformerEmbeddingBackend(
        _project_path(model["local_path"]),
        repo_id=model["repo_id"],
        revision=model["revision"],
        device=model.get("device", "cpu"),
        allow_model_download=False,
    )
    return SemanticIntentRouter(
        embedding_backend=backend,
        index_path=_project_path(approved["path"]),
        index_sha256_path=_project_path(approved["sha256_path"]),
        metadata_path=_project_path(approved["metadata_path"]),
        aggregation_method=config["aggregation"],
        per_intent_family_limit=int(config["per_intent_family_limit"]),
        precomputed_index_store=PrecomputedIndexEmbeddingStore(
            artifact_path=_project_path(embeddings["path"]),
            sha256_path=_project_path(embeddings["sha256_path"]),
        ),
    )


def clear_production_semantic_router_cache() -> None:
    """Test/development hook; production calls normally retain the cached model."""

    load_production_semantic_router.cache_clear()
    _load_validated_config_cached.cache_clear()


def _automatic_guard_reasons(keyword_result: Any, query: str) -> tuple[str, ...]:
    reason = _AUTOMATIC_GUARD_INTENTS.get(keyword_result.legacy_query_type)
    reasons = [reason] if reason and keyword_result.is_explicit_match else []
    if re.search(
        r"\b(?:privacy|private|anonymous|anonymised|anonymized|confidential)\b",
        query.casefold(),
    ):
        reasons.append("privacy_guard")
    if re.search(
        r"\b(?:post|publish|upload|send|email|open|reveal|inspect|alter|change)\b"
        r".{0,100}\b(?:my account|private|another (?:student|learner)|other students?|"
        r"underlying (?:activity )?log|on my behalf)\b|"
        r"\b(?:another (?:student|learner)|other students?)\b.{0,100}"
        r"\b(?:record|dashboard|figures?|activity)\b",
        query.casefold(),
    ):
        reasons.append("external_action_guard")
    if (
        keyword_result.legacy_query_type == "dashboard_interpretation"
        and re.search(
            r"\bwhy (?:is|are) my\b.{0,80}\b(?:engagement|activity|viewing|views?|participation)\b"
            r".{0,40}\b(?:low|weak|down|limited)\b",
            query.casefold(),
        )
    ):
        reasons.append("dashboard_interpretation_guard")
    return _normalise_guard_reasons(reasons)


def route_production_intent(
    query: str,
    *,
    current_page: str | None = None,
    mode: str | None = None,
    protected_guard_reasons: Sequence[str] = (),
    semantic_runtime: Any | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> ProductionIntentDecision:
    """Select one legacy C_FULL intent with conservative semantic fallback."""

    keyword = classify_query_detailed(query)
    try:
        routing_mode = resolve_intent_router_mode(mode)
    except Exception as exc:
        return ProductionIntentDecision(
            routing_mode=KEYWORD_BASELINE,
            keyword_intent=keyword.legacy_query_type,
            keyword_rule_id=keyword.rule_id,
            semantic_status="not_run",
            semantic_candidate=None,
            semantic_score=None,
            semantic_margin=None,
            semantic_accepted=False,
            selected_intent=keyword.legacy_query_type,
            routing_source="keyword_fallback",
            fallback_reason=f"invalid_mode:{type(exc).__name__}",
            protected_guard_reasons=(),
        )

    guards = _normalise_guard_reasons(
        (*protected_guard_reasons, *_automatic_guard_reasons(keyword, query))
    )
    if routing_mode == KEYWORD_BASELINE:
        return ProductionIntentDecision(
            routing_mode=routing_mode,
            keyword_intent=keyword.legacy_query_type,
            keyword_rule_id=keyword.rule_id,
            semantic_status="not_run",
            semantic_candidate=None,
            semantic_score=None,
            semantic_margin=None,
            semantic_accepted=False,
            selected_intent=keyword.legacy_query_type,
            routing_source="keyword",
            fallback_reason="keyword_baseline_mode",
            protected_guard_reasons=guards,
        )
    if guards:
        guarded_intent = keyword.legacy_query_type
        if any(reason in guards for reason in ("privacy_guard", "external_action_guard")):
            guarded_intent = "access_or_capability_question"
        return ProductionIntentDecision(
            routing_mode=routing_mode,
            keyword_intent=keyword.legacy_query_type,
            keyword_rule_id=keyword.rule_id,
            semantic_status="not_run",
            semantic_candidate=None,
            semantic_score=None,
            semantic_margin=None,
            semantic_accepted=False,
            selected_intent=guarded_intent,
            routing_source="keyword_guard",
            fallback_reason="protected_deterministic_guard:" + ",".join(guards),
            protected_guard_reasons=guards,
        )

    try:
        resolved_config_path = str(Path(config_path).resolve())
        config = _load_validated_config_cached(resolved_config_path)
        runtime = semantic_runtime or load_production_semantic_router(resolved_config_path)
        prediction = runtime.predict(
            query,
            current_page=current_page,
            aggregate_all_examples=bool(config["aggregate_all_examples"]),
        )
        result = prediction.result
        candidate = result.winning_label
        score = result.winning_score
        margin = result.margin
        standard_gate = bool(
            score is not None
            and margin is not None
            and score >= float(config["semantic_score_threshold"])
            and margin >= float(config["semantic_margin_threshold"])
        )
        oos_score = getattr(result, "out_of_scope_score", score)
        oos_gate = bool(
            oos_score is not None
            and margin is not None
            and oos_score >= float(config["oos_score_threshold"])
            and margin >= float(config["oos_margin_threshold"])
        )
        social_guard = _is_pure_social_interaction(query)
        if social_guard:
            semantic_effective = bool(candidate == "social_interaction" and standard_gate)
            return ProductionIntentDecision(
                routing_mode=routing_mode,
                keyword_intent=keyword.legacy_query_type,
                keyword_rule_id=keyword.rule_id,
                semantic_status=result.status,
                semantic_candidate=candidate,
                semantic_score=score,
                semantic_margin=margin,
                semantic_accepted=semantic_effective,
                selected_intent="social_interaction",
                routing_source="semantic" if semantic_effective else "conversational_guard",
                fallback_reason="" if semantic_effective else "class_level_social_guard",
                protected_guard_reasons=guards,
            )
        if result.status != "available":
            reason = prediction.reason or result.status
        elif candidate == "out_of_scope" and oos_gate:
            return ProductionIntentDecision(
                routing_mode=routing_mode,
                keyword_intent=keyword.legacy_query_type,
                keyword_rule_id=keyword.rule_id,
                semantic_status=result.status,
                semantic_candidate=candidate,
                semantic_score=score,
                semantic_margin=margin,
                semantic_accepted=True,
                selected_intent=candidate,
                routing_source="semantic_special_outcome",
                fallback_reason="",
                protected_guard_reasons=guards,
            )
        elif candidate in {"social_interaction", "unsupported_task", "ambiguous"} and standard_gate:
            return ProductionIntentDecision(
                routing_mode=routing_mode,
                keyword_intent=keyword.legacy_query_type,
                keyword_rule_id=keyword.rule_id,
                semantic_status=result.status,
                semantic_candidate=candidate,
                semantic_score=score,
                semantic_margin=margin,
                semantic_accepted=True,
                selected_intent=candidate,
                routing_source="semantic_special_outcome",
                fallback_reason="",
                protected_guard_reasons=guards,
            )
        elif candidate in FUTURE_SCOPE_OUTCOMES or candidate not in LEGACY_QUERY_TYPES:
            reason = f"special_semantic_outcome:{candidate or 'none'}"
        elif score is None or score < float(config["semantic_score_threshold"]):
            reason = "semantic_score_below_threshold"
        elif margin is None or margin < float(config["semantic_margin_threshold"]):
            reason = "semantic_margin_below_threshold"
        else:
            return ProductionIntentDecision(
                routing_mode=routing_mode,
                keyword_intent=keyword.legacy_query_type,
                keyword_rule_id=keyword.rule_id,
                semantic_status=result.status,
                semantic_candidate=candidate,
                semantic_score=score,
                semantic_margin=margin,
                semantic_accepted=True,
                selected_intent=candidate,
                routing_source="semantic",
                fallback_reason="",
                protected_guard_reasons=guards,
            )
        if keyword.rule_id == "UNMATCHED_DEFAULT":
            return _uncertain_decision(
                routing_mode=routing_mode,
                keyword=keyword,
                semantic_status=result.status,
                candidate=candidate,
                score=score,
                margin=margin,
                reason=reason,
                guards=guards,
            )
        explicit_conflict = _explicit_heuristic_conflict_reason(
            keyword=keyword,
            query=query,
            result=result,
        )
        if explicit_conflict:
            return _uncertain_decision(
                routing_mode=routing_mode,
                keyword=keyword,
                semantic_status=result.status,
                candidate=candidate,
                score=score,
                margin=margin,
                reason=reason,
                guards=guards,
                uncertainty_basis=f"explicit_heuristic_conflict:{explicit_conflict}",
            )
        return ProductionIntentDecision(
            routing_mode=routing_mode,
            keyword_intent=keyword.legacy_query_type,
            keyword_rule_id=keyword.rule_id,
            semantic_status=result.status,
            semantic_candidate=candidate,
            semantic_score=score,
            semantic_margin=margin,
            semantic_accepted=False,
            selected_intent=keyword.legacy_query_type,
            routing_source="keyword_fallback",
            fallback_reason=reason,
            protected_guard_reasons=guards,
        )
    except Exception as exc:
        reason = f"semantic_runtime_error:{type(exc).__name__}"
        if keyword.rule_id == "UNMATCHED_DEFAULT":
            return _uncertain_decision(
                routing_mode=routing_mode,
                keyword=keyword,
                semantic_status="error",
                candidate=None,
                score=None,
                margin=None,
                reason=reason,
                guards=guards,
            )
        return ProductionIntentDecision(
            routing_mode=routing_mode,
            keyword_intent=keyword.legacy_query_type,
            keyword_rule_id=keyword.rule_id,
            semantic_status="error",
            semantic_candidate=None,
            semantic_score=None,
            semantic_margin=None,
            semantic_accepted=False,
            selected_intent=keyword.legacy_query_type,
            routing_source="keyword_fallback",
            fallback_reason=reason,
            protected_guard_reasons=guards,
        )
