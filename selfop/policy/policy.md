# policy.md

This document defines the structural and syntactical rules you MUST follow when creating or editing files inside `Codex` home. The allowed editable space is **SKILL.md + references/ only**.

---

## 1. Directory Structure

```
.                            ← codex agent home
└── skills/
    └── {skill_name}/
        ├── SKILL.md         ← required; the agent's entry point (Tier 1 — always loaded)
        └── references/      ← optional; on-demand docs (Tier 2 — loaded only when the model wants to based on how SKILL.md directs)
```

- Only one skill directory may exist under `skills/`. Do not create additional skill directories.
- Every skill directory MUST contain a `SKILL.md` file.
- The `references/` folder is optional. Place supplementary docs here that the skill loads on demand.
- Each reference file MUST be cited in `SKILL.md` using the path from codex home: `~/.codex/skills/{skill_name}/references/<slug>.md`.

---

## 2. SKILL.md Syntax

### Frontmatter (required)

```md
---
name: skill-name
description: When this skill should and should not trigger.
---
```

- Both `name` and `description` are **required**.
- `description` controls implicit matching — front-load key use cases and trigger words.

### Body

The body after the frontmatter contains the skill's instructions. Upper limit: **5,000 words**. 

[SKILL.md](http://SKILL.md) is automatically loaded into agents context when the skill activates, in the beginning of the run. It serves as the main entry point and orchestrator for the entire task — all high-level strategy, sequencing of steps, delegation decisions, and references to supporting documents must originate here.

---

## 3. references/

- Use for specialized documentation, examples, schemas, checklists, or context that would bloat SKILL.md if inlined.
- Each reference file upper limit: **5,000 words**.
- Keep references focused — one topic per file. The agent is more likely to follow a targeted reference than a long omnibus document.

### Critical behavioral constraint

**SKILL.md is the only guaranteed-loaded artifact.** Files in `references/` are loaded on demand — the agent will only read them if SKILL.md explicitly instructs it to. Without such instructions, agent might not read the references.

---

## 4. Built-in Sub-Agents

Three built-in agents are available in Codex:


| Name       | Purpose                                   | Sandbox   |
| ---------- | ----------------------------------------- | --------- |
| `default`  | General-purpose fallback                  | inherited |
| `worker`   | Execution-focused (implementation, fixes) | inherited |
| `explorer` | Read-heavy codebase exploration           | read-only |


### Critical behavioral constraints

- **SKILL.md must explicitly direct sub-agent usage (if needed).** The agent will not spawn sub-agents on its own unless SKILL.md instructs when to delegate, which agent type to use, and what task to hand off. Without explicit instructions, sub-agents might go unused.
- **Sub-agents *maybe* fire-and-forget from a context perspective.** They do not see the parent's full history unless context is explicitly done so.
- **Fixed runtime limits apply.** `max_threads = 6` (concurrent thread cap), `max_depth = 1` (no recursive delegation — sub-agents cannot spawn their own sub-agents), `job_max_runtime_seconds = 1800` (30-minute per-worker timeout). These configs are not configurable through the skill.

---

## 5. Agent Runtime Tools

The agent has access to the following tools during task execution. SKILL.md instructions should be written with awareness of these capabilities — the agent cannot do anything beyond what these tools provide.

### Shell & file manipulation


| Tool           | Purpose                                                                                      |
| -------------- | -------------------------------------------------------------------------------------------- |
| `exec_command` | Run shell commands (bash). Primary tool for all filesystem, build, and execution operations. |
| `write_stdin`  | Send input to a running process started by `exec_command`.                                   |
| `apply_patch`  | Apply a unified diff patch to files. Used for code edits.                                    |
| `view_image`   | View an image file from the workspace.                                                       |


### Planning & goal tracking


| Tool          | Purpose                                                  |
| ------------- | -------------------------------------------------------- |
| `update_plan` | Create or update a structured plan for the current task. |
| `get_goal`    | Retrieve the current goal.                               |
| `create_goal` | Set a new goal for the session.                          |
| `update_goal` | Modify the current goal.                                 |


### Sub-agent management (via `tool_search`)

These tools *maybe* are **deferred** — the agent *might have to* first call `tool_search` to discover them before use.


| Tool           | Purpose                                                  |
| -------------- | -------------------------------------------------------- |
| `spawn_agent`  | Create a sub-agent (`default`, `worker`, or `explorer`). |
| `send_input`   | Send a message to a running sub-agent.                   |
| `resume_agent` | Resume a closed sub-agent thread.                        |
| `wait_agent`   | Wait for a sub-agent to finish.                          |
| `close_agent`  | Close a sub-agent thread.                                |


### Discovery


| Tool          | Purpose                                                                                           |
| ------------- | ------------------------------------------------------------------------------------------------- |
| `tool_search` | Search for deferred tools (e.g., sub-agent tools). Must be called before using any deferred tool. |


### Not available

The following are **not enabled** in the task execution environment: `web_search`, `image_generation`, MCP servers, plugins, custom agent definitions.

---

## 7. Design Rules

1. **One skill only.** Do not create additional skill directories under `skills/`.
2. **SKILL.md is the control plane.** If you want the agent to use a reference or a sub-agent, SKILL.md must say so explicitly.
3. **References** should be used for specialized documentation, task information, examples, schemas, checklists, or context that would bloat SKILL.md if inlined  — make sure to not add conflicting information between main skill and reference docs.
4. **Respect the context window.** SKILL.md is always loaded in full. Each reference adds to context only when read by the agent on-demand. Avoid bloating either — concise, actionable instructions outperform verbose ones.
5. **Prevent drift.** Write instructions that explicitly constrain what the agent should and should NOT do. Negative instructions are as important as positive ones.
