"""Preserve vLLM metric labels and histogram buckets; never take just the first series."""
import math

from prometheus_client.parser import text_string_to_metric_families


def parse_engine_metrics(text):
    return [{"name": sample.name, "labels": dict(sample.labels), "value": sample.value}
            for family in text_string_to_metric_families(text)
            for sample in family.samples
            if sample.name.startswith("vllm:") and math.isfinite(sample.value)]


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
