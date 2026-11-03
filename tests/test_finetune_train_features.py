"""Data preparation for the LoRA training script. No torch or transformers needed: the tokenizer is a stand-in."""
import pytest

from finetune.train_lora import END_OF_TURN, IGNORE, build_dataset, build_features, collate


class FakeTokenizer:
    """One id per character, so lengths and positions are easy to reason about."""

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        text = "".join(f"<{m['role']}>{m['content']}" for m in messages)
        return text + ("<assistant>" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}


MESSAGES = [{"role": "system", "content": "rules"}, {"role": "user", "content": "q?"},
            {"role": "assistant", "content": "answer"}]


def test_only_the_answer_and_end_of_turn_are_trained_on():
    feature = build_features(MESSAGES, FakeTokenizer(), 1000)
    prompt = "<system>rules<user>q?<assistant>"
    answer = "answer" + END_OF_TURN
    assert len(feature["input_ids"]) == len(prompt) + len(answer) == len(feature["labels"]) == len(feature["attention_mask"])
    assert feature["labels"][:len(prompt)] == [IGNORE] * len(prompt)
    assert "".join(chr(i) for i in feature["labels"][len(prompt):]) == answer
    assert feature["input_ids"][len(prompt):] == feature["labels"][len(prompt):]


def test_examples_longer_than_the_limit_are_dropped_not_cut_short():
    features, dropped = build_dataset([{"messages": MESSAGES}], FakeTokenizer(), 10)
    assert features == [] and dropped == 1  # cutting would lose the end of the answer or its Sources section
    features, dropped = build_dataset([{"messages": MESSAGES}], FakeTokenizer(), 1000)
    assert len(features) == 1 and dropped == 0


def test_the_last_message_must_be_the_answer():
    with pytest.raises(ValueError):
        build_features(MESSAGES[:2], FakeTokenizer(), 1000)


def test_padding_is_neither_attended_to_nor_trained_on():
    short = build_features(MESSAGES, FakeTokenizer(), 1000)
    long = build_features([MESSAGES[0], {"role": "user", "content": "a much longer question?"}, MESSAGES[2]],
                          FakeTokenizer(), 1000)
    batch = collate([short, long], pad_id=0)
    assert len({len(row) for row in batch["input_ids"]}) == 1
    pad = len(long["input_ids"]) - len(short["input_ids"])
    assert batch["attention_mask"][0][-pad:] == [0] * pad and batch["labels"][0][-pad:] == [IGNORE] * pad
    assert batch["input_ids"][0][-pad:] == [0] * pad
