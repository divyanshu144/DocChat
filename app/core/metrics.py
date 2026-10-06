"""Single-worker Prometheus registry; no prompt, identity, or model-name labels."""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

_BUCKETS = (.01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 20, 40, 80, 160, 320)
_STAGES = {"planner", "retriever", "synthesizer", "grounding", "critic",
           "retrieval.embedding_init", "retrieval.embedding", "retrieval.search",
           "retrieval.reranking", "answer.persistence"}
_PROVIDERS = {"local", "groq", "openai", "mistral"}


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter("docchat_requests_total", "Completed HTTP requests",
                                ["route", "method", "outcome", "status_class"], registry=self.registry)
        self.inflight = Gauge("docchat_requests_inflight", "Active HTTP requests", registry=self.registry)
        self.latency = Histogram("docchat_request_duration_seconds", "Full HTTP response duration",
                                 ["route", "outcome"], buckets=_BUCKETS, registry=self.registry)
        self.first_answer = Histogram("docchat_first_answer_seconds", "First answer SSE delivery",
                                      ["route"], buckets=_BUCKETS, registry=self.registry)
        self.stages = Histogram("docchat_stage_duration_seconds", "Pipeline stage latency",
                               ["stage", "outcome"], buckets=_BUCKETS, registry=self.registry)
        self.attempts = Counter("docchat_llm_attempts_total", "Application-visible model attempts",
                                ["provider", "outcome"], registry=self.registry)
        self.generation = Histogram("docchat_llm_duration_seconds", "Model attempt duration",
                                    ["provider", "outcome"], buckets=_BUCKETS, registry=self.registry)
        self.ttft = Histogram("docchat_llm_ttft_seconds", "Time to first nonempty model content",
                              ["provider"], buckets=_BUCKETS, registry=self.registry)
        self.tokens = Counter("docchat_llm_tokens_total", "Provider-reported tokens only",
                              ["provider", "direction"], registry=self.registry)
        self.missing_usage = Counter("docchat_llm_missing_usage_total", "Attempts missing output usage",
                                     ["provider"], registry=self.registry)
        self.retries = Counter("docchat_llm_retries_total", "Explicit application LLM retries",
                               ["provider"], registry=self.registry)
        self.retrieval_failures = Counter("docchat_retrieval_failures_total", "Failed retrieval stages",
                                         registry=self.registry)
        self.empty_retrieval = Counter("docchat_empty_retrieval_total", "Retrieval returned no chunks",
                                      registry=self.registry)
        self.critic_parse = Counter("docchat_critic_parse_failures_total", "Invalid critic JSON",
                                    registry=self.registry)
        self.replans = Counter("docchat_replans_total", "Critic requested another graph pass",
                               registry=self.registry)

    def observe(self, record):
        event = record.get("event")
        outcome = record.get("outcome", "ok")
        outcome = outcome if outcome in {"ok", "error", "cancelled"} else "error"
        if event == "request_started" and record.get("transport") == "http":
            self.inflight.inc()
        elif event == "request" and record.get("transport") == "http":
            self.inflight.dec()
            route = record.get("route") or "unmatched"
            method = record.get("method", "OTHER")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                method = "OTHER"
            status_class = f"{record.get('status_code', 500) // 100}xx"
            self.requests.labels(route, method, outcome, status_class).inc()
            self.latency.labels(route, outcome).observe(record["duration_s"])
            if record.get("first_answer_s") is not None:
                self.first_answer.labels(route).observe(record["first_answer_s"])
        elif event == "llm_retry":
            provider = record.get("provider")
            self.retries.labels(provider if provider in _PROVIDERS else "other").inc()
        elif event == "span":
            name = record.get("name")
            if name in _STAGES:
                self.stages.labels(name, outcome).observe(record["duration_s"])
            if name == "retriever":
                if record.get("retrieval_failed") or outcome == "error":
                    self.retrieval_failures.inc()
                if record.get("retrieved_chunks_count") == 0:
                    self.empty_retrieval.inc()
            if name == "critic":
                if record.get("critic_parse_failed"):
                    self.critic_parse.inc()
                if record.get("needs_replan"):
                    self.replans.inc()
            if name == "llm.attempt":
                provider = record.get("provider")
                provider = provider if provider in _PROVIDERS else "other"
                self.attempts.labels(provider, outcome).inc()
                self.generation.labels(provider, outcome).observe(record["duration_s"])
                if record.get("ttft_s") is not None:
                    self.ttft.labels(provider).observe(record["ttft_s"])
                for direction, key in (("input", "prompt_tokens"), ("output", "completion_tokens")):
                    if type(record.get(key)) is int and record[key] >= 0:
                        self.tokens.labels(provider, direction).inc(record[key])
                if record.get("completion_tokens") is None:
                    self.missing_usage.labels(provider).inc()


metrics = Metrics()
