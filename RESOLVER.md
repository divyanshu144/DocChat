# RESOLVER.md

Scan the task description and current file context for the keywords below.
Load the matching skill file **before** responding. This file is loaded automatically
at session start via the CLAUDE.md reference.

## Routing Table

| Keywords | Skill file | Load when |
|----------|-----------|-----------|
| `agent` `graph` `node` `critic` `planner` `retriever` `synthesizer` `AgentState` `replan` `LangGraph` | `.claude/skills/langgraph/SKILL.md` | Touching the agent pipeline |
| `ingest` `pdf` `youtube` `web` `chroma` `embed` `chunk` `collection` `source_id` | `.claude/skills/ingestion/SKILL.md` | Touching data ingestion or ChromaDB |
| Any implementation or debugging task | `.claude/skills/conventions.md` | Default: load unless task is clearly read-only (explaining, reviewing, answering questions) |

## Loading Rules

1. **`conventions.md` is near-default** — load it for any implementation, debugging, or code-change task. Skip only when the task is purely read-only (explaining, reviewing, answering architecture questions).
2. **Domain skills are conditional** — load `langgraph/SKILL.md` or `ingestion/SKILL.md` only when the task touches their domain (keyword match or file context).
3. **Load at most 2 files per response** — one domain skill + `conventions.md`. If two domain skills both match, load the primary (most keyword matches; tie → file being edited) and note the other.
4. **When the 2-file cap drops a relevant domain skill**, say at the top of the response: "Note: this task also touches [domain] — invoke `/[skill]` if you need that context."
5. **Process skills are never auto-loaded** — `fde-plan`, `fde-review`, `api-conventions`, `debug-playbook`, `pr-checklist` are user-invoked only.

## Growth Rules

- Add a keyword row when a new domain skill is created. Grep for false-positive matches before committing.
- Promote `.claude/skills/conventions.md` to a folder if it exceeds ~200 lines or a third domain with different convention needs appears.
- Duplication between a process skill and `conventions.md` is acceptable — the trigger mechanism difference justifies it.
