# Fine-tune data tooling

Everything needed to build, check and generate the data for the grounded-answer LoRA fine-tune. Design:
`docs/superpowers/specs/2026-11-02-litellm-lora-finetune-design.md`. Nothing here needs a GPU. Steps that call a teacher
model need an OpenAI-compatible endpoint and cost money, so they are run only after the cost is approved.

| Step | Command | Output |
|---|---|---|
| Pick GOV.UK guides | `python -m finetune.discover_govuk` | a selection list (already folded into `manifest.json`) |
| Download sources | `python -m finetune.fetch_sources` | `data/finetune/raw/` (git-ignored), `sources.lock.json` (sha256 per file) |
| Build the corpus | `python -m finetune.corpus` | `data/finetune/corpus/*.points.jsonl` (git-ignored) |
| Check documents for leakage | `python -m finetune.check_documents` | `document-leakage-report.json` |
| Generate examples (teacher, billable) | `python -m finetune.generate_examples --base-url ... --model ...` | `data/finetune/examples.raw.jsonl` |
| Validate and de-duplicate | `python -m finetune.validate_examples examples.raw.jsonl --output examples.jsonl --report report.json` | passing examples plus a review sample |
| Check examples for leakage | `python -m finetune.decontaminate examples.jsonl --hashes-out hashes.json` | fails loudly on any overlap |
| Build the held-out set (teacher, billable) | `python -m eval.prepare_heldout_v2 --base-url ... --model ...` | `data/finetune/heldout-v2-workload.json` |

**What is committed:** the code, `manifest.json` (every document with URL, licence and split), `sources.lock.json`
(hashes only) and `document-leakage-report.json`. Downloaded documents, corpora, generated examples, weights and adapters
are git-ignored.

**Licences:** GOV.UK guides are Crown copyright published under the Open Government Licence
(<https://www.gov.uk/help/terms-conditions>). The NIST publications each state that they are not subject to copyright in the
United States. The working-time PDF and the Wikipedia RAG article used by the existing evaluation are never sources.

**Splits are by document.** `excluded` documents stay in the manifest for the record but are used for nothing: they shared
text with a held-out document (see each document's `note`).
