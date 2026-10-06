# Phase 1 implementation plan

1. Establish offline baseline and preserve unrelated working files.
2. Add local inference contract/transport, client ownership and configuration.
3. Add request/span telemetry and instrument API/MCP, graph and retrieval boundaries.
4. Add serving readiness, deployment manifest template and operational documentation.
5. Test malformed streams, missing usage, failures/cancellation, configuration changes,
   request isolation, first answer timing, and compatibility with existing callers.
6. Run Ruff and the full non-eval suite; update handoff with live acceptance still pending.

Phases 2–4 remain the agreed follow-up: sustained benchmark + Prometheus metrics,
held-out retrieval/answer evaluation, then capacity planning and optional engines.
