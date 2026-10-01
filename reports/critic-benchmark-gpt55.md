# Critic diagnostic with GPT-5.5, 2026-10-01

The user approved the 20-case API benchmark and selected `gpt-5.5`. This run used
OpenAI Chat Completions, reasoning_effort=none, temperature=0, a 150-token output
cap, no provider fallback and a five-minute overall timeout. The existing critic
prompt was unchanged apart from targeting original_query. Production model/provider
settings were not changed; environment overrides affected this process only.

| Set | Correct | TP | FP | FN | TN | API/parse errors |
|---|---:|---:|---:|---:|---:|---:|
| Hand-written edge cases | 5/5 | 1 | 0 | 0 | 4 | 0 |
| Generated corruptions | 15/15 | 15 | 0 | 0 | 0 | 0 |

Edge-case poor-class precision, recall and F1 were 1.00. Generated corruptions had
recall 1.00; their all-poor labels cannot measure false positives or useful precision.
All 20 completions ended with finish_reason=stop. API usage reported 7,081 input
tokens, 653 output tokens, zero cached tokens and zero reasoning tokens.

At the documented standard rates of $5/M input and $30/M output, this usage is an
estimated $0.054995, about 5.5 US cents, before any account-specific billing adjustment.
This is a calculation from returned token counts, not a billing receipt.
[Official model documentation](https://developers.openai.com/api/docs/models/gpt-5.5)
lists the rates and supported reasoning settings; the
[model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.5)
describes none for short classification workloads.

[Raw JSON](critic_benchmark_gpt55.json) retains each verdict, raw response, usage,
finish reason and run settings. Malformed responses count as errors rather than
silently becoming correct good verdicts from the critic's fail-open fallback.

Reproduce only when paid API calls are authorized:

```bash
LLM_PROVIDER=openai OPENAI_CHAT_MODEL=gpt-5.5 OPENAI_REASONING_EFFORT=none \
FALLBACK_LLM_PROVIDER=none LANGSMITH_TRACING=false \
venv/bin/python eval/benchmark.py --output reports/critic_benchmark_gpt55.json
```

One run on five deliberately difficult edge cases and fifteen generated corruptions
is a small diagnostic, not a production accuracy claim. It measures classification,
not answer-quality improvement from the retry loop. No grounding redesign or
context-aware critic ablation was implemented or executed here.
