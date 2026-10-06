# Serving foundation — Phase 1

Approved direction: extend DocChat's existing local/vLLM provider and graph without
changing prompts, ranking, verification, or answer-release behavior.

- Preserve chat_complete() -> str and chat_stream() -> async text iterator.
- Add immutable request/result types and an OpenAI-compatible local adapter.
- Own HTTP/SDK clients by event loop and configuration; close them at API/MCP shutdown.
- Validate local endpoint/model, configure bounded HTTP timeouts and pool limits.
- Emit content-free JSON timing records with request/span/parent IDs. Measure graph
  stages, retrieval embedding/search/ranking and individual LLM attempts. Stream TTFT
  means first nonempty content; nonstream TTFT and server queue wait remain unknown.
- Observe HTTP through final response-body delivery, including cancellation and SSE
  errors. Preserve existing response framing and headers. Trace MCP queries too.
- Add a separate local serving readiness route. It must not make ordinary health
  checks or application startup depend on an optional remote GPU.
- No GPU launch, paid evaluation, provider configuration change, production critic
  redesign, Prometheus endpoint or benchmark schema migration in this phase.

Acceptance: offline transport/lifecycle/tracing tests and existing regression gates;
live GPU/full-document acceptance explicitly pending an available approved endpoint.
