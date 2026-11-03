"""QLoRA fine-tune of a chat model on the grounded-answer examples.

Runs on a rented GPU, never on the laptop. `torch`, `transformers`, `peft` and `bitsandbytes` are imported inside
`main()` so that the data preparation below can be tested without them (see `requirements-finetune.txt`).

The loss is computed on the assistant answer only. The prompt (system message, retrieved context, question) is the exact
text the serving path sends, and it is masked out, so the model learns to write answers and not to recite contexts.

Everything that affects the result is written to `run.json` next to the adapter: hyperparameters, library versions,
the per-epoch losses, wall-clock time and the sha256 of the adapter file. Adapters are never committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

IGNORE = -100
END_OF_TURN = "<|im_end|>"  # the end-of-turn token Qwen's chat template closes every turn with


def load_examples(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build_features(messages: list[dict], tokenizer, max_len: int, end_of_turn: str = END_OF_TURN) -> dict | None:
    """Token ids and labels for one example, or None when it does not fit in `max_len`.

    `messages` ends with the assistant answer. The prompt is rendered with the model's own chat template and the
    generation prefix, then the answer and the end-of-turn token are appended; only those get labels.
    """
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("the last message must be the assistant answer")
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(messages[-1]["content"] + end_of_turn, add_special_tokens=False)["input_ids"]
    ids = prompt_ids + answer_ids
    if len(ids) > max_len:
        return None
    return {"input_ids": ids, "labels": [IGNORE] * len(prompt_ids) + answer_ids, "attention_mask": [1] * len(ids)}


def build_dataset(examples: list[dict], tokenizer, max_len: int) -> tuple[list[dict], int]:
    features, dropped = [], 0
    for example in examples:
        feature = build_features(example["messages"], tokenizer, max_len)
        if feature is None:
            dropped += 1
        else:
            features.append(feature)
    return features, dropped


def collate(batch: list[dict], pad_id: int) -> dict:
    """Right-pad a batch. Padding is never attended to and never trained on."""
    longest = max(len(item["input_ids"]) for item in batch)
    out: dict[str, list] = {"input_ids": [], "labels": [], "attention_mask": []}
    for item in batch:
        pad = longest - len(item["input_ids"])
        out["input_ids"].append(item["input_ids"] + [pad_id] * pad)
        out["labels"].append(item["labels"] + [IGNORE] * pad)
        out["attention_mask"].append(item["attention_mask"] + [0] * pad)
    return out


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="directory for the adapter and run.json")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--max-steps", type=int, default=-1, help="a few steps for the smoke run; -1 trains fully")
    parser.add_argument("--max-len", type=int, default=5120)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    import peft
    import torch
    import transformers
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments

    random.seed(args.seed)
    transformers.set_seed(args.seed)
    started = time.time()
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    train, dropped_train = build_dataset(load_examples(args.train), tokenizer, args.max_len)
    valid, dropped_valid = build_dataset(load_examples(args.validation), tokenizer, args.max_len)
    if not train or not valid:
        raise SystemExit("no usable examples after tokenising")

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(args.base_model, quantization_config=quant, torch_dtype=torch.bfloat16,
                                                 device_map={"": 0}, attn_implementation="sdpa")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    lora = LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)
    trainable, total = model.get_nb_trainable_parameters()

    args.output.mkdir(parents=True, exist_ok=True)
    training_args = TrainingArguments(
        output_dir=str(args.output / "checkpoints"), num_train_epochs=args.epochs, max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size, per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum, learning_rate=args.lr, lr_scheduler_type="cosine",
        warmup_ratio=0.03, weight_decay=0.0, bf16=True, logging_steps=5, eval_strategy="epoch", save_strategy="epoch",
        save_total_limit=2, load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False,
        seed=args.seed, data_seed=args.seed, report_to=[], remove_unused_columns=False, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False})
    if args.max_steps > 0:  # smoke run: evaluate at the end of the few steps instead of at an epoch boundary
        training_args.eval_strategy, training_args.save_strategy = "no", "no"
        training_args.load_best_model_at_end = False
    trainer = Trainer(model=model, args=training_args, train_dataset=train, eval_dataset=valid,
                      data_collator=lambda batch: {k: torch.tensor(v) for k, v in collate(batch, pad_id).items()})
    result = trainer.train()
    final_eval = trainer.evaluate() if args.max_steps <= 0 else {}

    adapter_dir = args.output / "adapter"
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    weights = next(adapter_dir.glob("adapter_model.*"))
    record = {
        "base_model": args.base_model, "seed": args.seed,
        "hyperparameters": {"rank": args.rank, "alpha": args.alpha, "dropout": args.dropout, "lr": args.lr,
                            "epochs": args.epochs, "max_steps": args.max_steps, "max_len": args.max_len,
                            "batch_size": args.batch_size, "grad_accum": args.grad_accum,
                            "effective_batch": args.batch_size * args.grad_accum, "scheduler": "cosine",
                            "warmup_ratio": 0.03, "quantisation": "nf4 4-bit, double quant, bf16 compute",
                            "target_modules": lora.target_modules},
        "data": {"train_examples": len(train), "validation_examples": len(valid),
                 "dropped_too_long": {"train": dropped_train, "validation": dropped_valid},
                 "train_sha256": sha256_of(args.train), "validation_sha256": sha256_of(args.validation)},
        "parameters": {"trainable": trainable, "total": total},
        "versions": {"torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__,
                     "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0)},
        "train_metrics": result.metrics, "final_eval": final_eval, "log_history": trainer.state.log_history,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "wall_clock_s": round(time.time() - started, 1),
        "adapter_file": weights.name, "adapter_sha256": sha256_of(weights),
    }
    (args.output / "run.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(json.dumps({k: record[k] for k in ("train_metrics", "final_eval", "wall_clock_s", "adapter_sha256")}, default=str))


if __name__ == "__main__":
    main()
