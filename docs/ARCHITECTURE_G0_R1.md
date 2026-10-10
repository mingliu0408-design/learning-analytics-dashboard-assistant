# Restored public application architecture

```mermaid
flowchart LR
 U[Streamlit five pages] --> S[Per-session and per-task adapter]
 S --> R[REPLAY: immutable saved answer]
 S --> P[P3 exact provider requests in parent]
 P --> W[Credential-free worker]
 S -->|explicit COMPONENTS gates| W
 W --> E[Scoped Evidence]
 W --> G[Single-gated original R0]
 W --> M[Complete M1 import and read]
 M --> DB[Session copy of read-only native seed]
 E --> C[P1 and i5 typed planner / compiler]
 G --> C
 M --> C
 C --> A[Parent provider candidate / bounded repair]
 A --> V[Worker encoded constraint checks]
 V --> F[Parent FINAL provider]
 F --> K[Worker final and citation checks]
 K --> U
 Q[Evaluation Gold and rating references] -. evaluation only .-> X[Research checks]
```

The main API/UI process never imports original M1 or its network-denial guard. All core source/Memory work is isolated in the child; parent provider SDK receives an explicit in-memory visitor key. Worker environment uses an allowlist and no provider credentials. A real localhost HTTP fixture checked three P3 calls, candidate and FINAL across the complete M1 boundary.

REPLAY does not generate. COMPONENTS demand comes from explicit checkboxes, uses lexical Memory and has no P3 inference or natural-language model answer. LIVE uses the exact original frozen role payloads and complete source service. Optional Hybrid resources are required when the P3 Memory bit is true; no silent lexical replacement is labelled Hybrid. Encoded plan and permitted-reference checks are preserved, with no semantic-quality guarantee.

Each visitor owns separate key/history/workspace. Every task's native seed is copied into that workspace before writing, and original SQLite, graph and source events stay read-only. Corrective writes preserve USER role, consent, source events, links and supersession. Public evaluation data is a separate sidecar and source ingestion rejects Gold fields.
