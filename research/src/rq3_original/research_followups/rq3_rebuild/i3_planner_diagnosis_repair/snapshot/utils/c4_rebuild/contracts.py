"""One mode contract and immutable request boundary, separate from RQ2 labels."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Any
from utils.c4_dashboard_scoped.scope import Scope, canonical, digest
from utils.c4_real_contracts import P3CapabilityRoute


class Mode(str, Enum):
    S0_PAGE_ONLY = "S0_PAGE_ONLY"
    S1_CROSS_PAGE_EVIDENCE = "S1_CROSS_PAGE_EVIDENCE"
    S2_EVIDENCE_RAG = "S2_EVIDENCE_RAG"
    S3_EVIDENCE_MEMORY = "S3_EVIDENCE_MEMORY"
    S4_EVIDENCE_PLANNING = "S4_EVIDENCE_PLANNING"
    S5_FULL = "S5_FULL"


# Evidence, RAG, Memory, Planning; provisional development configurations.
POLICIES = dict(zip(Mode, [(False, False, False, False), (True, False, False, False),
    (True, True, False, False), (True, False, True, False),
    (True, False, False, True), (True, True, True, True)]))
FUTURE_POLICIES = ("RECONFIRM_FOR_SCHEDULE", "WARN_SNAPSHOT_ONLY")


@dataclass(frozen=True)
class Access:
    rag: bool = False
    memory: bool = False
    planning: bool = False
    authority_id: str | None = None

    def __post_init__(self):
        if any(type(getattr(self, x)) is not bool for x in ('rag', 'memory', 'planning')):
            raise TypeError('Access bits must be explicit booleans')
        if any((self.rag, self.memory, self.planning)) and not self.authority_id:
            raise ValueError('Permission needs a runtime authority reference')


@dataclass(frozen=True)
class Request:
    scope: Scope
    query: str
    page: str
    as_of: str
    session_id: str
    mode: Mode
    future_policy: str  # Deliberately no default scientific policy.
    history: tuple = ()
    access: Access = field(default_factory=Access)
    # These optional fields must come from explicit visible UI controls.
    task_intent: str | None = None
    memory_purpose: str | None = None
    visible_controls: str | None = None
    schedule_timezone: str | None = None
    allowed_windows: tuple = ()
    schedule_horizon: dict | None = None
    memory_state_version: str = "UNBOUND"
    source_version: str = "UNBOUND"

    def __post_init__(self):
        object.__setattr__(self, 'mode', Mode(self.mode))
        if self.future_policy not in FUTURE_POLICIES:
            raise ValueError('Explicit future policy required')
        if (self.task_intent or self.memory_purpose) and not self.visible_controls:
            raise ValueError('Explicit intent/purpose requires a visible control receipt')
        if not self.query.strip() or not self.session_id:
            raise ValueError('Query and session required')
        if any(set(x) != {'role', 'content'} or x['role'] not in ('user', 'assistant')
               or not isinstance(x['content'], str) for x in self.history):
            raise ValueError('Only legitimate visible user/assistant turns accepted')
        reject_sidecars(self.__dict__)


def reject_sidecars(value):
    """Closed runtime constructors plus recursive rejection, not a string DLP claim."""
    forbidden = {'gold', 'expected', 'expected_ids', 'expected_fact_ids', 'labels',
                 'ratings', 'human_rating', 'test_only', 'case_id', 'family_id', 'fixture_name'}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in forbidden or str(key).lower().startswith(('test_only_', 'expected_')):
                raise ValueError('Evaluation sidecar field in runtime: ' + str(key))
            reject_sidecars(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_sidecars(item)


class Router(Protocol):
    def route(self, primary_input) -> P3CapabilityRoute: ...


class Retriever(Protocol):
    identity: str
    def retrieve(self, request: Request): ...


class Memory(Protocol):
    identity: str
    def read(self, request: Request, purpose: str): ...


class LiveExecutionDisabled(RuntimeError):
    pass


def execute_live(*args, **kwargs):
    raise LiveExecutionDisabled('I0 has no live transport, SDK factory or credentials path')
