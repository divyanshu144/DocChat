#!/bin/bash
# Daily resume of the Groq judging run for the fine-tune evaluation (see HANDOFF.md, item 2a).
# Judges the pair-balanced batches in order; each call resumes where the last stopped and
# exits non-zero when Groq's daily token limit is hit, which ends today's work.
# When every row of every batch is judged, it removes its own launchd job.
# Never prints keys: the app reads them from .env.
set -u
cd "$(dirname "$0")/.." || exit 1
EVAL=data/finetune/eval
LOCK=$EVAL/.judge-daily.lock
LOG=$EVAL/judge-daily.log

if ! mkdir "$LOCK" 2>/dev/null; then echo "$(date -u +%FT%TZ) another run holds the lock, exiting" >> "$LOG"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

echo "$(date -u +%FT%TZ) start" >> "$LOG"
for ids in "$EVAL"/judge-batch-*.ids.json; do
  venv/bin/python -m eval.judge_answer_review_pack \
    --pack $EVAL/pack-v2.jsonl --output $EVAL/labels-v2-groq.jsonl \
    --judge-provider groq --judge-model openai/gpt-oss-120b --prompt-version v1 \
    --ids-file "$ids" >> "$LOG" 2>&1 || { echo "$(date -u +%FT%TZ) stopped in $ids (daily limit or error)" >> "$LOG"; break; }
done

left=$(venv/bin/python - <<'EOF'
import glob, json
want = {i for f in glob.glob("data/finetune/eval/judge-batch-*.ids.json") for i in json.load(open(f))}
have = {json.loads(l)["blind_id"] for l in open("data/finetune/eval/labels-v2-groq.jsonl")}
print(len(want - have))
EOF
)
echo "$(date -u +%FT%TZ) unjudged rows left: $left" >> "$LOG"
if [ "$left" = "0" ]; then
  echo "$(date -u +%FT%TZ) ALL BATCHES JUDGED, removing the launchd job" >> "$LOG"
  launchctl bootout "gui/$(id -u)/com.docchat.judge-daily" 2>> "$LOG"
fi
