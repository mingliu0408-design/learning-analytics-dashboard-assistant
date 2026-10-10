"""M1 adapter: native read/reopen authority, no evaluation-sidecar dependency."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import sys
from utils.c4_dashboard_scoped.scope import digest
from .contracts import reject_sidecars

ROOT = Path(__file__).resolve().parents[2]
M1 = ROOT/'research_followups/rq3_rebuild/m1_memory_completeness'


def clone_native_states(databases, destination):
    """Explicit closed SQLite clones; all destinations are new temporary states."""
    import sqlite3
    from contextlib import closing
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    clones = {}
    for course, source in databases.items():
        target = destination/(digest(course)+'.sqlite')
        with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('NATIVE_CLONE_INTEGRITY')
        clones[course] = target
    return clones


def m1_dependencies():
    if str(M1/'code') not in sys.path:
        sys.path.insert(0, str(M1/'code'))
    import m1_common  # Frozen dependency installs a network guard, no model imports.
    from relations import read_bundle, compile_sidecar
    from state_harness import ReadOnlyStore
    return read_bundle, compile_sidecar, ReadOnlyStore


@dataclass(frozen=True)
class MemoryBundle:
    envelope: dict
    authority: dict
    trace: dict


class NativeM1:
    """Explicit candidate; backend=None is lexical, never advertised as hybrid."""
    def __init__(self, databases, graph, source_events, *, backend=None, expand=True):
        self.databases = dict(databases)
        self.graph = deepcopy(graph)
        self.source_events = deepcopy(source_events)
        self.backend = backend
        self.expand = bool(expand)
        self.identity = ('M1_HYBRID' if backend is not None else 'M1_LEXICAL') + ('_LINKS_DEV_CANDIDATE' if expand else '_UNEXPANDED_DIAGNOSTIC')
        self.calls = 0

    def read_envelope(self, target, purpose):
        read_bundle, _, _ = m1_dependencies()
        return read_bundle(self.databases, self.graph, dict(target=target, purpose=purpose),
                           expand=self.expand, backend=self.backend)

    def read(self, request, purpose):
        read_bundle, _, ReadOnlyStore = m1_dependencies()
        target = dict(learner_id=request.scope.learner_id, course_id=request.scope.course_id,
                      session_id=request.session_id, as_of=request.as_of,
                      horizon='current explicitly scoped request', query=request.query,
                      page=request.page, visible_history=list(request.history),
                      visibility_rule='Only supplied legitimate visible turns')
        envelope, trace = self.read_envelope(target, purpose)
        self.calls += 1
        authority = self.authority_for(envelope.payload, trace['original_seed_items'])
        reject_sidecars(envelope.payload)
        return MemoryBundle(envelope.payload, authority, dict(
            identity=self.identity, readonly_state_unchanged=trace['readonly_state_unchanged'],
            original_seed_ids=trace['original_seed_ids'], kept_facts=trace['kept_facts'],
            added_facts=trace['added_facts'], exclusions=trace['exclusions'],
            omitted_facts=trace['omitted_facts'], graph_sha256=trace['graph_sha256'],
            native_state_sha256=trace['original_read']['before_logical_sha256']))

    def authority_for(self, envelope, seed_items=()):
        """Check selected saved/live native IDs against the explicitly scoped store.

        For saved-envelope reproduction, this is new authority from a recreated
        synthetic source state, never a claim of original captured telemetry.
        """
        _, _, ReadOnlyStore = m1_dependencies()
        authority = {}
        seeds = {n['memory_id']: n for n in seed_items}
        target = envelope['scope']
        # Re-open the same native store, no state mutation and no source alias IDs.
        with ReadOnlyStore(self.databases[target['course_id']], clock=lambda: target['as_of']) as store:
            for f in envelope['facts']:
                mid = f['native_id']
                rec = store.get_memory(target['learner_id'], mid)
                event = self.source_events.get(f['source_ref']['event_id'])
                authority[mid] = dict(native_record=rec.as_dict() if rec else None,
                    enabled=store.is_memory_enabled(target['learner_id']),
                    current_version=str(rec.version) if rec else None,
                    current_as_of=target['as_of'], source_event=event,
                    relevance_components=deepcopy(seeds[mid]['relevance_components']) if mid in seeds else None,
                    relevance_status='NATIVE_SEED_SCORE' if mid in seeds else 'NOT_SCORED_LINK_EXPANSION')
        return authority
