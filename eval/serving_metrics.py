"""Preserve engine metric labels and histogram buckets; never take just the first series."""
import math

from prometheus_client.parser import text_string_to_metric_families

# Metric-name prefix per serving engine. The request path is an OpenAI-compatible HTTP API and needs no engine switch;
# only metrics parsing is engine-specific.
ENGINE_METRIC_PREFIXES = {"vllm": ("vllm:",), "sglang": ("sglang:",)}
ENGINE_METRIC_STATUS = {
    "vllm": "series names observed on vLLM v0.30.0 by the legacy harness (2026-09-30); other versions not verified",
    "sglang": "UNVERIFIED: the sglang: prefix and series names have not been observed against a live SGLang server",
}
# Counters used for the per-cell prefix-cache hit rate (vLLM only). The first name is what v0.30.0 exposes; the older
# names are fallbacks kept from the legacy harness and are not verified here.
PREFIX_CACHE_COUNTERS = {
    "queries": ("vllm:prefix_cache_queries_total", "vllm:gpu_prefix_cache_queries_total"),
    "hits": ("vllm:prefix_cache_hits_total", "vllm:gpu_prefix_cache_hits_total"),
}


def parse_engine_metrics(text, prefixes=ENGINE_METRIC_PREFIXES["vllm"]):
    return [{"name": sample.name, "labels": dict(sample.labels), "value": sample.value}
            for family in text_string_to_metric_families(text)
            for sample in family.samples
            if sample.name.startswith(tuple(prefixes)) and math.isfinite(sample.value)]


def counter_changes(first, last):
    """Deltas by complete series identity; reset/new/disappeared series stay unknown."""
    def index(samples):
        return {(row["name"], tuple(sorted(row["labels"].items()))): row["value"]
                for row in samples if row["name"].endswith(("_total", "_count", "_sum", "_bucket"))}
    before, after = index(first), index(last)
    rows = []
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key), after.get(key)
        reset = a is not None and b is not None and b < a
        rows.append({"name": key[0], "labels": dict(key[1]), "reset": reset,
                     "delta": b - a if a is not None and b is not None and not reset else None})
    return rows


def prefix_cache_summary(changes, engine="vllm"):
    """Per-cell prefix-cache hit rate (in tokens) from counter changes, or an explicit unavailable reason."""
    def unavailable(reason):
        return {"status": "unavailable", "reason": reason}
    if engine != "vllm":
        return unavailable(f"metric names for engine {engine!r} are unverified; no hit rate is derived")
    if changes is None:
        return unavailable("no counter changes recorded for this cell")
    found = {}
    for kind, names in PREFIX_CACHE_COUNTERS.items():
        for name in names:
            rows = [row for row in changes if row["name"] == name]
            if rows:
                found[kind] = (name, rows)
                break
    if len(found) < 2:
        return unavailable("no prefix-cache counters in /metrics for this engine version")
    if any(row["reset"] or row["delta"] is None for _, rows in found.values() for row in rows):
        return unavailable("a prefix-cache counter reset or changed identity during the cell")
    queries = sum(row["delta"] for row in found["queries"][1])
    hits = sum(row["delta"] for row in found["hits"][1])
    if queries <= 0:
        return unavailable("no prefix-cache queries during the cell")
    return {"status": "ok", "queries": queries, "hits": hits, "hit_rate": hits / queries,
            "queries_metric": found["queries"][0], "hits_metric": found["hits"][0], "unit": "tokens"}
