set -eu
export PATH=/opt/venv/bin:$PATH
export HF_HOME=/workspace/huggingface
label=$1
model=$2
quant=${3:-}
mkdir -p /workspace/quantization
if [ -f /workspace/quantization/server.pid ]; then
  oldpid=$(cat /workspace/quantization/server.pid)
  kill -- -"$oldpid" 2>/dev/null || true
  sleep 5
fi
args=(serve "$model" --served-model-name Qwen2.5-7B-Instruct --host 127.0.0.1 --port 8000 --dtype float16 --max-model-len 16384 --gpu-memory-utilization 0.90 --enable-prefix-caching)
if [ -n "$quant" ]; then args+=(--quantization "$quant"); fi
nohup setsid vllm "${args[@]}" > "/workspace/quantization/$label-server.log" 2>&1 < /dev/null &
echo $! > /workspace/quantization/server.pid
echo "STARTED $label"
