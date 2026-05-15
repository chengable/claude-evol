# claude-evol — Self-Evolving Plugin for Claude Code

[中文](README.md)

Ports Hermes' autonomous evolution capabilities to Claude Code. Automatically detects repeated patterns, learns from errors, and accumulates domain knowledge—generating three categories of evolution suggestions (Skill/CLAUDE.md/Rule) to make Claude Code smarter over time.

## Features

- **Auto-detection**: Hooks count in the background; when thresholds are reached, notifies you at the next session
- **Three-category evolution**: Review agent classifies information as Skill (how-to), CLAUDE.md (what-to-remember), or Rule (must/must-not)
- **Manual trigger**: `/claude-evol` command initiates an evolution review anytime
- **Auto mode**: `/claude-evol auto` toggles automatic writing—skip per-category confirmation
- **Safe & conservative**: User confirmation mode by default + negative list + incremental updates

## Directory Structure

```
claude-evol/
├── .claude-plugin/
│   ├── plugin.json                    # Plugin manifest
│   └── marketplace.json               # Marketplace metadata
├── skills/
│   └── claude-evol/
│       └── SKILL.md                   # Main orchestration skill
├── agents/
│   └── claude-evol-reviewer.md        # Review agent (three-category classifier)
├── hooks/
│   └── hooks.json                     # PostToolUse/Stop/SessionStart hooks
├── scripts/
│   ├── state-manager.py               # State manager (stdlib only)
│   └── requirements.txt               # Python >= 3.8
└── README.md
```

## Installation

### Add Marketplace

```bash
/plugin marketplace add chengable/claude-evol
```

### Install Plugin

```bash
/plugin install claude-evol
```

Hooks take effect immediately after installation. No extra configuration needed. Use `/claude-evol` to manually trigger a review.

## Usage

### Manual Trigger

```
/claude-evol
```

Starts an evolution review immediately. The review agent analyzes the current session and generates three categories of suggestions:
- **Skill suggestions**: Reusable workflows (new umbrella skill / patch existing skill)
- **CLAUDE.md suggestions**: Project knowledge / user experience (incremental update, never overwrites unrelated content)
- **Rule suggestions**: Mandatory constraints (one `.md` file per constraint in `.claude/rule/`)

### Auto Mode

```
/claude-evol auto
```

Toggles auto-write mode. When enabled, review suggestions are written directly to files without per-category confirmation.

### Background Auto-Trigger

No manual action needed. Hooks work in the background:

```
PostToolUse Hook → increment (every tool call +1)
       ↓
Stop Hook → check-all --set-flag (write flag file when threshold reached)
       ↓
SessionStart Hook → get-pending (check for flag, notify user)
       ↓
User sees notification → /claude-evol or ignore
```

Default thresholds: Skill 10 tool iterations, Memory 10 tool iterations (matches Hermes).

## Three-Category Evolution Logic

The review agent classifies information from conversations into three categories:

| Target | Essence | Trigger Signals |
|--------|---------|-----------------|
| **Skill** | How to do | Repeated patterns (≥3x), error→resolution workflow, tool combinations, domain knowledge |
| **CLAUDE.md** | What to remember | User corrections, project facts, experience summaries, correct/incorrect experiences |
| **.claude/rule/** | Must / Must not | Hard constraints, security requirements, code standards, compatibility limits |

```
Information found in conversation
  ├─ Reusable operational workflow?   → Skill
  ├─ Project/user memory?            → CLAUDE.md
  └─ Mandatory constraint/rule?      → .claude/rule/
```

## Component Chain

```
skills/claude-evol/SKILL.md (orchestrator)
  ├── [Fork] agents/claude-evol-reviewer.md (review agent, haiku model)
  │     ├── Analyze conversation → three-category classification
  │     └── Output: structured JSON suggestions
  ├── [Call] scripts/state-manager.py (read/write evol_state.json)
  └── [Write] skills/, CLAUDE.md, .claude/rule/

hooks/hooks.json
  ├── PostToolUse → state-manager.py increment
  ├── Stop        → state-manager.py check-all --set-flag
  └── SessionStart → state-manager.py get-pending
```

## Marketplace

`marketplace.json` is located in `.claude-plugin/` for automatic discovery by the Claude Code plugin marketplace:

```json
{
  "name": "claude-evol",
  "owner": {
    "name": "chengable"
  },
  "plugins": [
    {
      "name": "claude-evol",
      "version": "1.0.0",
      "source": "./",
      "category": "productivity"
    }
  ]
}
```

Update `plugins[0].version` when publishing a new version.

## Debugging

```bash
# View full state
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-state

# Reset all state
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py reset-all

# Check specific counter
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get _iters_since_review

# Check transcript path for pending review
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-transcript
```

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Hook performance overhead | state-manager.py single-file JSON read/write, <1ms |
| Context window overflow | Review agent receives summary, not full conversation |
| Self-reinforcing loops | Negative list + user confirmation mode by default |
| Classification inaccuracy | Review prompt includes explicit criteria and examples |
| Cross-project state pollution | State files stored per-project under `.claude/` |

## Uninstall

```bash
/plugin disable claude-evol
/plugin uninstall claude-evol
/plugin marketplace remove chengable/claude-evol
```

## License

MIT
