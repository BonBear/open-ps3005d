#!/usr/bin/env bash
set -euo pipefail

MEMORY_DIR=".agents/memory"
mkdir -p "$MEMORY_DIR"

# 1. Create .claude/ symlinks so Claude Code / Claude Desktop discovers agents & skills automatically
mkdir -p .claude
ln -sfn ../.agents/agents .claude/agents
ln -sfn ../.agents/skills .claude/skills
echo "Linked .claude/agents and .claude/skills -> .agents/"

# 2. Ensure .agents/memory/ and .secrets/ are git-ignored
if [ -f ".gitignore" ]; then
    if ! grep -qF ".agents/memory" ".gitignore"; then
        printf "\n# Local AI agent memory\n.agents/memory/\n" >> .gitignore
        echo "Added .agents/memory/ to .gitignore"
    fi
else
    printf "# Local AI agent memory\n.agents/memory/\n.env\n.secrets/\n" > .gitignore
    echo "Created .gitignore with .agents/memory/, .env, and .secrets/"
fi

# 3. Create project_state.md if missing
if [ ! -f "$MEMORY_DIR/project_state.md" ]; then
    cat << 'EOF' > "$MEMORY_DIR/project_state.md"
# Project State

> Shared project board maintained by `orchestrator`. Read by all subagents before starting a task.
> Do NOT store secrets, tokens, or credentials here.

## 1. Architecture & Core Invariants
- **Summary**: _Populated from `AGENTS.md` and codebase inspection._
- **Key Subsystems**:
  - _TBD_
- **Critical Invariants**:
  - _See Section 1 of `AGENTS.md`._

## 2. Active Milestones & Current Focus
- [ ] Initial repository setup and agent onboarding

## 3. Open Blockers & Questions
- _None currently recorded._

## 4. Recent Completed Work (Rolling Log)
- Initialized `.agents/memory/` workspace.
EOF
    echo "Created $MEMORY_DIR/project_state.md"
fi

# 4. Create orchestrator.md if missing
if [ ! -f "$MEMORY_DIR/orchestrator.md" ]; then
    cat << 'EOF' > "$MEMORY_DIR/orchestrator.md"
# Orchestrator Memory

> Maintained by `orchestrator`. Tracks user preferences, model tiering effectiveness, and task decomposition patterns.

## 1. User Preferences & Workflow Rules
- **Git Discipline**: Never commit unless explicitly instructed. Never stage `.agents/memory/` or secrets.
- **Direct vs. Delegated**: Execute single-file fixes and quick questions directly; spin up subagents only for multi-file features, complex architecture changes, or broad audits.
- **Docs Hygiene**: Keep documentation DRY — link between docs instead of duplicating content.

## 2. Model Tiering Lessons
- **`haiku` / `flash_lite`**: Best for `janitor` and simple `researcher` symbol/file lookups.
- **`sonnet` / `flash`**: Default for `researcher`, standard `reviewer` runs, and routine `coder` tasks.
- **`inherit` / `opus` / `pro`**: Reserved for `architect` and complex `coder`/`reviewer` tasks (core architecture, concurrency, security audits).

## 3. Task Decomposition Patterns
- _Record project-specific workflow patterns here as they emerge._
EOF
    echo "Created $MEMORY_DIR/orchestrator.md"
fi

# 5. Create memory files for all subagents if missing
for agent in researcher architect coder reviewer janitor; do
    agent_file="$MEMORY_DIR/${agent}.md"
    if [ ! -f "$agent_file" ]; then
        cat << EOF > "$agent_file"
# ${agent^} Memory

> Reusable learnings, codebase patterns, and pitfalls recorded by \`${agent}\`.
> Compact via \`janitor\` when this file exceeds ~150 lines. Never store secrets here.

## Key Learnings & Patterns
- _No entries yet._
EOF
        echo "Created $agent_file"
    fi
done

echo "✅ Agent memory directory ($MEMORY_DIR) and .claude/ links are ready."
