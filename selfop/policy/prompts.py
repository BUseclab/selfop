"""Prompt fragments describing the optimizer's editable space (SKILL.md + references)."""

AGENT_HOME_DESCRIPTION = """\
# THE AGENT'S HOME DIRECTORY (ORCHESTRATION DIRECTORY)

The agent uses a **skill** as its entry point for the task. When the agent \
starts, it loads `SKILL.md` — the instruction file that tells it what to do, \
how to approach the problem, and when to pull in additional resources. The \
skill is the agent's operating manual.

From `SKILL.md` the agent can load reference docs from `references/` on demand. \
The skill orchestrates the agent's entire approach; editing it is how you steer behavior.

This is what `agent_home/` looks like:

```
agent_home/
└── skills/
    └── {skill_name}/
        ├── SKILL.md        ← the agent's entry point (loaded every run)
        └── references/     ← specialized docs the agent loads on demand
```

You are provided a `policy.md` file that contains the guidelines and policies to \
edit the agent's orchestration. You MUST follow these policies to edit the agent's \
orchestration (i.e. `agent_home/`). You can use `bash policy_checker.sh` to check if the \
edited agent's home directory follows the syntactical/structural guidelines defined in `policy.md`.\
"""

ANALYSIS_SCOPE_HINT = "SKILL.md and references"
