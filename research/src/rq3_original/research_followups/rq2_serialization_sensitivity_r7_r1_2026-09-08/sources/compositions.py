"""Pure frozen P1/P2/P3/P4 composition rules."""

from __future__ import annotations

from typing import Any, Mapping


class CompositionError(ValueError):
    """Raised when a frozen component is absent or malformed."""


Signature = tuple[bool, bool, bool]


def signature(value: Mapping[str, Any]) -> Signature:
    required = ("rag_required", "memory_required", "planning_required")
    if set(required) - set(value):
        raise CompositionError("complete capability signature is missing a required bit")
    bits = tuple(value[key] for key in required)
    if any(type(bit) is not bool for bit in bits):
        raise CompositionError("complete capability signature bits must be booleans")
    return bits  # type: ignore[return-value]


def signature_dict(value: Signature) -> dict[str, bool]:
    return {
        "rag_required": value[0],
        "memory_required": value[1],
        "planning_required": value[2],
    }


def compose_case(
    deterministic: Mapping[str, Mapping[str, Any]],
    b4: Mapping[str, Any],
    rag_specialist: Mapping[str, Any],
    memory_specialist: Mapping[str, Any],
) -> tuple[dict[str, Signature], dict[str, Any]]:
    """Return all eleven complete methods without label-level fallback mixing."""

    required = {
        "R2V2-D0_ALWAYS_ON",
        "R2V2-D1_NEVER_ON",
        "R2V2-B0_RULE",
        "R2V2-B1_LEGACY_INTENT",
        "R2V2-B2_PROTOTYPE",
        "R2V2-B3_OVR",
    }
    missing = sorted(required - set(deterministic))
    if missing:
        raise CompositionError(f"missing deterministic components: {missing}")
    direct = {method_id: signature(deterministic[method_id]) for method_id in required}
    b4_signature = signature(b4)
    if set(rag_specialist) != {"rag_required"} or type(
        rag_specialist["rag_required"]
    ) is not bool:
        raise CompositionError("RAG Specialist prediction is not the strict one-bit schema")
    if set(memory_specialist) != {"memory_required"} or type(
        memory_specialist["memory_required"]
    ) is not bool:
        raise CompositionError("Memory Specialist prediction is not the strict one-bit schema")

    unanimous = (
        direct["R2V2-B0_RULE"]
        == direct["R2V2-B2_PROTOTYPE"]
        == direct["R2V2-B3_OVR"]
    )
    p1_triggered = not unanimous
    p1 = b4_signature if p1_triggered else direct["R2V2-B3_OVR"]
    p2 = (rag_specialist["rag_required"], b4_signature[1], b4_signature[2])
    p3 = (
        rag_specialist["rag_required"],
        memory_specialist["memory_required"],
        b4_signature[2],
    )
    p4 = (b4_signature[0], memory_specialist["memory_required"], b4_signature[2])

    methods = {
        **direct,
        "R2V2-B4_JOINT_LLM": b4_signature,
        "R2V2-P1_HYBRID": p1,
        "R2V2-P2_RAG_SPECIALIST_COMPOSITION": p2,
        "R2V2-P3_RAG_MEMORY_SPECIALISTS": p3,
        "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION": p4,
    }
    return methods, {
        "p1_policy_id": "P1-C08-NONUNANIMOUS",
        "p1_triggered": p1_triggered,
        "p1_selected_complete_signature_source": (
            "R2V2-B4_JOINT_LLM" if p1_triggered else "R2V2-B3_OVR"
        ),
        "p4_status": "POST_DEV_EXPLORATORY_ABLATION",
    }
