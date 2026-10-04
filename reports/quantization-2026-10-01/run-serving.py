import os, subprocess, sys, json
from datetime import datetime, timezone
from pathlib import Path
label=sys.argv[1]
out=Path('reports/quantization-2026-10-01')
env=dict(os.environ, LLM_PROVIDER='local', FALLBACK_LLM_PROVIDER='none', LOCAL_BASE_URL='http://127.0.0.1:18000/v1', LOCAL_CHAT_MODEL='Qwen2.5-7B-Instruct', LOCAL_API_KEY='', CRITIC_REJECTION_LOG='', PYTHONPATH='.', PYTHONUNBUFFERED='1')
steps=[('control',['-m','eval.positive_control','--prompts-file','data/bench_prompts.jsonl']),('quality',['eval/benchmark.py','--output',str(out/f'{label}-quality.json')]),('sweep',['-m','eval.inference_benchmark','--providers','local','--prompts-file','data/bench_prompts.jsonl','--concurrency','1,16,64','--max-tokens','1400','--gpu-cost-per-hr','1.09','--out',str(out/f'{label}-speed.jsonl')])]
for step,args in steps:
    print(datetime.now(timezone.utc).isoformat(), label, step, flush=True)
    with (out/f'{label}-{step}.log').open('w') as f:
        r=subprocess.run(['venv/bin/python',*args],env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1100)
    print('exit',r.returncode,flush=True)
    if r.returncode: sys.exit(r.returncode)
    if step=='quality':
        d=json.loads((out/f'{label}-quality.json').read_text())
        print('quality',d['edge_metrics'],d['generated_metrics'],flush=True)
print('DONE',label,flush=True)
