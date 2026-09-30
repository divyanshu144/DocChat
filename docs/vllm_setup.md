# vLLM Setup & Launch — Self-Hosted `local` Provider

Companion runbook to `docs/superpowers/specs/2026-09-28-inference-benchmarking-design.md`.
This is manual, operational, and billed — nothing here runs in CI or unattended. Follow it
in order: rent → serve → smoke-test → **stop the box**.

Model: **Qwen2.5-7B-Instruct** (Apache-2.0, ungated — no HF token/license-accept needed).
Substitute `meta-llama/Llama-3.1-8B-Instruct` throughout if you'd rather use the fallback
noted in the spec; it requires an `HF_TOKEN` with the license accepted on huggingface.co.

---

## 1. Rent a GPU

Any single 24GB GPU handles a 7–8B model in FP16 comfortably (~15GB weights + KV cache
headroom). This runbook walks through **RunPod** concretely (cheapest/easiest on-ramp);
Lambda Labs and Vast.ai are viable alternatives with the same shape but different UI.

| Provider | GPU | Rough cost |
|---|---|---|
| RunPod (community cloud) | L4 or A10G, 24GB | ~$0.30–0.50/hr |
| Lambda Labs (on-demand) | A10, 24GB | ~$0.60/hr |
| Vast.ai | A10/L4/3090, 24GB | ~$0.20–0.40/hr (spot, less reliable) |

**RunPod, step by step:**

1. Sign up at runpod.io, add a small credit balance (billing is per-second while a pod
   runs).
2. **Deploy → Pods → + Deploy On-Demand**. Filter GPU type to **L4** or **A10** (24GB).
   Community Cloud pricing is cheaper than Secure Cloud and is fine for benchmarking.
3. **Template:** pick "RunPod PyTorch 2.x" (or any CUDA 12.x template) — it ships with
   NVIDIA drivers and Python already set up, so there's nothing to install at the driver
   layer.
4. **Container disk:** bump to at least 40GB (model weights are ~15GB; leaves room for
   the HF cache).
5. **Expose HTTP Ports:** add `8000`. RunPod puts a TLS-terminating reverse proxy in
   front of any port listed here and hands you back a URL shaped like
   `https://<pod-id>-8000.proxy.runpod.net` — note this is **https**, not plain
   `http://host:8000`; it changes the URLs used later in this runbook.
6. Deploy the pod. Once it's `Running`, open its **Connect → Web Terminal** (or use the
   SSH command RunPod shows, if you'd rather use your own terminal).

A RunPod pod is itself already a container with GPU passthrough — there is **no nested
Docker** here. vLLM gets installed and run directly inside the pod's own Python
environment, not via `docker run`.

## 2. Launch vLLM

In the pod's terminal:

```bash
pip install -U vllm

export VLLM_API_KEY=$(openssl rand -hex 24)   # keep this — you'll need it below
echo "vLLM API key: $VLLM_API_KEY"

# nohup + & so the server survives you closing the terminal/SSH session
nohup vllm serve Qwen/Qwen2.5-7B-Instruct \
  --served-model-name Qwen2.5-7B-Instruct \
  --port 8000 \
  --api-key "$VLLM_API_KEY" \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --dtype bfloat16 \
  > vllm.log 2>&1 &

tail -f vllm.log   # watch for "Application startup complete" — model download +
                    # CUDA graph capture takes a couple of minutes on first launch
```

Notes on the flags:

- **`--api-key`** — always set this. RunPod's proxy URL is reachable from the open
  internet the moment the port is exposed; an unauthenticated vLLM server is free
  inference for anyone, billed to your card.
- **`--served-model-name`** — the name clients send in `"model"`. Matches
  `LOCAL_CHAT_MODEL` in DocChat's `.env` (step 4).
- **`--gpu-memory-utilization 0.90`** — fraction of GPU memory vLLM is allowed to claim
  for weights + KV cache. Lower it (e.g. `0.80`) if you see CUDA OOM at startup on a
  smaller card.
- **`--max-model-len 8192`** — caps context length, which caps KV-cache memory. Raise it
  only if you need longer contexts and have headroom; this is usually the first thing to
  lower if you hit OOM.
- First request after startup is slow (model download + CUDA graph capture) — wait for
  `tail -f vllm.log` to show the server is up before drawing latency conclusions.

## 3. Health-check the server

From your own machine, using the RunPod proxy URL from step 1.5 (`https`, no port
number — the proxy terminates TLS and maps `:8000` internally):

```bash
export POD_URL=https://<pod-id>-8000.proxy.runpod.net

curl -s $POD_URL/v1/models \
  -H "Authorization: Bearer $VLLM_API_KEY" | python3 -m json.tool
```

Expect a JSON body listing `Qwen2.5-7B-Instruct`. Then a real chat completion:

```bash
curl -s $POD_URL/v1/chat/completions \
  -H "Authorization: Bearer $VLLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen2.5-7B-Instruct",
    "messages": [{"role": "user", "content": "Say hello in five words."}],
    "max_tokens": 32
  }' | python3 -m json.tool
```

If both return cleanly, the server is up and speaking the schema `_local_complete` /
`_local_stream` (`app/services/llm.py`) expect.

## 4. Point DocChat at it

In `.env` (not committed):

```bash
LLM_PROVIDER=local
LOCAL_BASE_URL=https://<pod-id>-8000.proxy.runpod.net/v1
LOCAL_CHAT_MODEL=Qwen2.5-7B-Instruct
LOCAL_API_KEY=<the $VLLM_API_KEY value from step 2>
```

## 5. App-level smoke test

Don't route a real chat request through the full agent graph yet — call the provider seam
directly first, so a failure is obviously the vLLM box and not planner/retriever/critic:

```bash
source venv/bin/activate
python3 -c "
import asyncio
from app.services.llm import chat_complete

async def main():
    result = await chat_complete([{'role': 'user', 'content': 'Say hello in five words.'}])
    print(result)

asyncio.run(main())
"
```

If that prints a real completion, `LLM_PROVIDER=local` is safe to use for a full
`/api/v1/chat` request or for Phase 2's `eval/inference_benchmark.py`.

## 6. Terminate the box

**Every time you're done for the session** — this is the step most likely to be skipped
and the one that actually controls cost. On RunPod: **Pods → your pod → Terminate**.

**Use Terminate, not Stop, to actually stop paying.** This was checked against real
billing data, not assumed: a pod that crashed within ~2 minutes and sat `EXITED` (i.e.
stopped, not terminated) for the following ~2.5 hours was billed **$1.87** for that
whole window — GPU compute billing did *not* stop while merely stopped. Only
**Terminate** reliably stopped the meter. Don't rely on Stop as a cost control here,
whatever the RunPod dashboard's own description of it implies — verify against your
account's billing history (`list-pod-billing` if you have the RunPod MCP tools, or the
console's billing page) rather than trusting the Stop/Terminate distinction at face
value.

Terminate does mean the disk is gone and the next run re-downloads the ~15GB model —
worth it compared to a repeat of the $1.87 outcome above.

---

## Troubleshooting

- **CUDA OOM on startup** — lower `--gpu-memory-utilization` (e.g. `0.80`) or
  `--max-model-len` (e.g. `4096`).
- **Model download is slow / times out** — pre-pull with
  `huggingface-cli download Qwen/Qwen2.5-7B-Instruct` on the pod before `vllm serve`, so
  the download happens once and isn't racing the server's own startup timeout.
- **`401 Unauthorized`** — the `Authorization: Bearer` value doesn't match `--api-key`,
  or the header wasn't sent. Re-check `LOCAL_API_KEY` in `.env` matches `$VLLM_API_KEY`
  exactly.
- **`502`/`504` from the RunPod proxy** — the server isn't up yet (still downloading the
  model or capturing CUDA graphs) or crashed on startup. Check `tail -f vllm.log` in the
  pod terminal.
- **Gated model (if you switch to Llama-3.1-8B-Instruct)** — accept the license on
  huggingface.co first, then `export HF_TOKEN=<token>` before running `vllm serve`.
