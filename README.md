# Project Handoff

[![Tests](https://github.com/zhentianzun/project-handoff/actions/workflows/test.yml/badge.svg)](https://github.com/zhentianzun/project-handoff/actions/workflows/test.yml)

**A Codex skill for picking up a project after changing agents, models, or conversations.**

[简体中文](README.zh-CN.md) · [Skill instructions](SKILL.md) · [Workflow](references/workflow.md)

Keep the last successful action, next action, decisions, ownership, and evidence in your project. A new agent reads that state before continuing. Small Python tools check whether the saved state still matches the workspace.

```text
Agent A → saved checkpoint + evidence + file ownership
                       ↓
Agent B → read state → check changes → reconcile unknown actions → continue
```

## What it does

- Creates an `AGENTS.md` entry, one authoritative state file, and generated task views.
- Saves checkpoints without marking unfinished work complete or hiding code changes.
- Rejects stale state writes, detects interrupted writes, and preserves existing manual rules.
- Tracks external operations; `running` or `unknown` results block blind continuation.
- Exports a handoff snapshot containing approved documents and code fingerprints.
- Works with Git and non-Git projects; the runtime needs Python 3.10+ and the standard library.

## Install

Download this repository into your personal Codex skills directory as `project-handoff`, or install it with your usual skill installer using this repository URL. Existing installations should be updated deliberately; avoid overwriting a customized skill.

On a new project, ask Codex:

```text
$project-handoff Set up automatic handoff for this project.
```

Once the project entry exists, agents using a host that loads `AGENTS.md` follow it without repeated reminders. Hosts without that support need their own entry configuration or the exported handoff snapshot. Open conversations should reread the latest entry when resuming.

## Try it without an agent

Run these from this repository. Use a **new, empty demo directory**:

```sh
mkdir demo-project
python scripts/init_project.py --root demo-project --name Demo
python scripts/init_project.py --root demo-project --name Demo --apply
cd demo-project
python tools/handoff.py checkpoint --owner agent-A --summary "Initialized the handoff; next: fill in project facts."
python tools/handoff.py check
python tools/handoff.py export --output .handoff-export
```

The first initializer command previews the plan. `--apply` creates the files. Existing handoff files or a tool with the same name are preserved by refusing initialization. For existing mechanisms, maintain their current source of truth instead.

For a real project, choose source directories explicitly, for example `--source src`. The default fingerprint covers only the handoff tool. **A passing check is not a product test or a deployment result.** Fill in the real environment, commands, decisions, open tasks, and verification evidence.

## Switching agents halfway through

Before editing, record task ownership and file scope. Save a checkpoint after each meaningful stage. Before an external action, record its ID, target, owner, status, and reconciliation procedure in `operations`.

The receiving agent confirms the previous writer has stopped or coordinated, reads the checkpoint, checks uncommitted changes, and reconciles unresolved actions. Do not call `record-local` just to silence a mismatch; it only records the current fingerprint and proves no business behavior.

State edits use the runtime's `load`, `validate`, and `save` API, then `render` and `check`. `save` uses a lock, atomic replacement, and a read-version comparison. These guards do not lock arbitrary source files or recover unsaved thoughts.

## Verification

```sh
python -X utf8 scripts/test_portability.py
```

24 isolated tests currently cover project roots, existing rules, checkpoints, stale writers, interrupted writes, code drift, unknown external results, and export boundaries. Git must be available for the Git-specific tests. A GitHub Actions matrix is included for Linux and Windows with Python 3.10 and 3.13; its results become available after publication.

These are tool-level tests, not proof that every model or host follows every instruction. Abrupt interruptions can lose information that was never saved. Secret-file exclusions are a practical filter, not a guarantee that arbitrary documents are safe to share; review exported documents and state before distributing them.

## Contributing

Please include a minimal reproduction and the expected handoff behavior when reporting a bug. Do not attach credentials, student data, production databases, or raw private conversations. Changes should preserve manual project rules and keep verification claims separate from implementation status.

Released under the [MIT License](LICENSE).

```sh
git clone https://github.com/zhentianzun/project-handoff.git ~/.codex/skills/project-handoff
```
