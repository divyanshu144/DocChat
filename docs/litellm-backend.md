# LiteLLM backend (opt-in)

`LLM_BACKEND=litellm` makes `chat_complete()` and `chat_stream()` call models through LiteLLM instead of the per-provider
code in `app/services/llm.py`. The default is `native` and nothing else changes. The public functions, the `usage_sink`, the
timing spans, the retry rules and the fallback chain are the same either way. The code is in `app/services/llm_litellm.py`.

This page is what was measured on 2026-11-02, with LiteLLM 1.83.0, on one Mac, against a local mock server. It is not a
comparison of real providers. No live provider was called, so **live parity is not claimed**.

## Turning it on

```bash
pip install -r requirements.txt -r requirements-litellm.txt
LLM_BACKEND=litellm uvicorn app.main:app
```

LiteLLM is not in `requirements.lock`, so the production images do not contain it. If the backend is selected and the
package is missing, the first call fails with a message pointing at `requirements-litellm.txt`.

## Why 1.83.0

`requirements.txt` pins `httpx<0.28`. LiteLLM needs `httpx>=0.28` from 1.83.3 onward (1.106.6 was the latest when this was
written), so 1.83.0 is the newest release that installs next to the existing pins (`pip check` is clean). In a scratch
environment with `httpx 0.28.1` and LiteLLM 1.106.6 the existing suite also passed (834 passed, 7 skipped), so lifting the
cap looks possible. That is a separate change, because it touches `requirements.lock` and the scanned images.

## How it matches the native behaviour

| Behaviour | How the LiteLLM backend does it |
|---|---|
| Keys and URLs | Passed per deployment from `settings`. A blank key raises a clear error, because LiteLLM would otherwise look for `GROQ_API_KEY` and similar in the environment on its own. `local` with no key gets the placeholder `none`. |
| Fallback chain | Groq models in order, then openai (when `FALLBACK_LLM_PROVIDER=openai` and that key exists). openai falls back to groq. mistral and local never fall back. `local` is never a fallback target. |
| What may fall back | Only errors that `_is_retryable_llm_error` accepts (429, 5xx, timeouts, connect errors). A 400 or 401 is raised. |
| Streaming | Falls back only before the first token. After that the error is raised. |
| Temperature | Sent only when asked for. For openai, a 400 that mentions `temperature` is retried once without it, the model is remembered, and a `llm_retry` event is emitted. |
| openai token limit | `max_completion_tokens` (and `reasoning_effort` when set), as in the native path. |
| Spans and usage | The same `llm.attempt` span fields, and `record_usage` / `usage_sink` filled from the response. |
| Logging | LiteLLM's loggers are held at WARNING (see below). |

## What LiteLLM does differently, and why the Router's own fallbacks are not used

Measured against a loopback server that returns chosen status codes:

1. **`Router(fallbacks=...)` falls back on any error**, including 400 and 401. The native code raises those, because
   retrying a bad request or a bad key on another provider hides a real fault.
2. **It continues a stream on the fallback model after tokens were already sent.** With a primary that failed after two
   tokens, the caller received `a, b` and then the fallback's full answer `a, b, c`, so the first words appeared twice.
   The native code never does this.

So the Router here has no fallbacks, no retries and no cooldowns (`num_retries=0`, `disable_cooldowns=True`), and the
chain is driven from our code using the existing retry classification. LiteLLM exceptions carry `status_code`, so that
classification works on them unchanged. `tests/test_llm_litellm.py` runs the real package against a loopback server to
keep these two facts from regressing.

3. **At DEBUG, LiteLLM logs whole prompts and request URLs.** With the root logger at DEBUG, a captured log held the
   prompt text and the URL. At INFO it did not. The backend clamps LiteLLM's loggers to WARNING when it loads the package,
   and a test checks that no prompt or URL reaches the logs at DEBUG. Without the clamp that test fails.
4. **Exceptions are LiteLLM types** (for example `ServiceUnavailableError`) rather than the Groq SDK's or `httpx`'s. The agent
   nodes catch no provider-specific type (`app/api/chat.py` logs a generic failure), and the status code is the same, but
   any future code that catches a vendor exception class would see a different class.
5. **Connect and pool timeouts are not set separately.** The Router gets one overall timeout (`INFERENCE_READ_TIMEOUT_S`).
   The native `httpx` client has separate connect, read, write and pool timeouts and a connection limit.
6. **No explicit shutdown.** `close_llm_clients()` closes the native clients. LiteLLM manages its own HTTP sessions, and the
   backend does not close them.
7. **Noisy Router log lines.** After a stream failure the Router logs an ERROR line ("Fallback also failed ...") even though
   it has no fallbacks configured. It contains the error message only.

## Parity check

`python -m eval.llm_backend_parity --calls 300` sends the same three prompts through both backends to one local mock
OpenAI-compatible server using the `local` provider (the only provider whose address both backends let us redirect), plus a
503. Results from three runs:

| What was compared | Result |
|---|---|
| Completion text | identical |
| Streamed text | identical |
| `usage_sink` (prompt tokens, completion tokens, finish reason) | identical |
| `llm.attempt` span fields | identical |
| Error status and retry classification | identical (503, retryable) |

Per-call time against a server that answers instantly (milliseconds, median over 300 calls, three runs). This measures
overhead only, on one machine, with a Python mock server that adds its own noise:

| | Complete | First token | Whole stream |
|---|---|---|---|
| native | 0.84 / 1.11 / 0.98 | 0.80 / 1.08 / 0.92 | 1.19 / 1.57 / 1.35 |
| litellm | 1.61 / 2.54 / 1.68 | 1.68 / 2.53 / 1.75 | 4.07 / 5.69 / 4.16 |

So LiteLLM adds roughly 0.7 to 1.4 ms per call and about 0.8 ms to the first token, and about 3 ms to a short stream. Against
a real provider call (hundreds of milliseconds and up) that is small. Only a very fast local model would notice it.

## Live check against Groq (2026-11-03)

`python -m eval.llm_backend_live_parity --reps 5` sent the same 3 short prompts to Groq (`openai/gpt-oss-120b`) through both
backends, alternating which went first, with the OpenAI fallback switched off. 15 complete and 15 streamed calls per backend.
Raw results: `reports/llm-backend-live-parity-2026-11-03.json`. One run, one afternoon, free-tier key.

| | native | litellm |
|---|---|---|
| Complete calls that worked | 15 of 15 | 12 of 15 (3 rate-limited, 429) |
| Streamed calls that worked | 15 of 15 | 10 of 15 (5 rate-limited, 429) |
| Finish reason, model, usage recorded | stop, same model, always | the same on every call that worked |
| Same text, complete (temperature 0) | n/a | 12 of 12 pairs identical |
| Same text, streamed (no temperature sent) | n/a | 7 of 10 pairs identical (the model is not deterministic here) |
| Bad key / unknown model | 401 / 404, not retryable | 401 / 404, not retryable |
| Median time, complete / first token | 0.48 s / 0.42 s | 0.43 s / 0.22 s (see below) |

**A real difference found: retries.** The native Groq client keeps the SDK default of 2 retries, so it quietly retried
brief 429s (the native calls that took 2.3 to 2.6 s). The LiteLLM backend uses `num_retries=0`, so it raised those 429s at once.
In the app that sends the request to the OpenAI fallback (a 429 is retryable), or fails if there is none. So on a rate-limited
key the LiteLLM backend is less forgiving than the native one. The timing rows are not a speed comparison: the LiteLLM medians
leave out the failed calls and the native ones include retry waits. Not fixed here; the options are `num_retries=2` on the
Router or a short retry in our wrapper, and either needs its own test.

Small differences: on a bad key LiteLLM raised `BadRequestError` carrying status 401 (native raised `AuthenticationError`).
The status and the retry classification match.

Not covered: OpenAI as the primary, Mistral, the groq to openai fallback on a real outage, concurrency, one model only.

## What it costs to carry

| | Without | With LiteLLM 1.83.0 |
|---|---|---|
| Packages in a venv built from `requirements.txt` | 139 | 155 (16 added, none changed version) |
| Installed size of that venv | 620 MB | 739 MB (the `litellm` package alone is 77 MB) |
| Importing the module | 0.4 s (`app.services.llm`, 678 modules loaded) | 1.3 s warm, 3.9 s the first time after install (about 2,560 modules loaded) |

Added packages: `aiohappyeyeballs aiohttp aiosignal fastuuid frozenlist importlib_metadata Jinja2 jiter litellm MarkupSafe
multidict openai propcache tiktoken yarl zipp`.

## Not measured

- Any real provider (Groq, OpenAI, Mistral): rate limits, real error bodies, real streaming usage chunks.
- Fallback parity on real providers. The native openai and groq clients cannot be pointed at the mock server, so the
  groq-to-openai chain is covered by unit tests and the loopback tests, not by a side-by-side run.
- Behaviour under concurrency, memory use, and long-running leaks.
- LiteLLM versions other than 1.83.0.
