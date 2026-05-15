---
name: claude-evol
description: This skill should be used when the user runs "/claude-evol", "/claude-evol auto", asks to "review conversations for learning", "check for evolution", "evolve from this session", "auto-evolve my skills", "find patterns to automate", or mentions claude-evol status checking.
version: 1.0.0
---

# claude-evol — Claude Code 自主进化编排器

## 概述

claude-evol 将 Hermes 自主进化能力移植到 Claude Code。它通过 Hook 自动计数 + Fork Agent 审查 + 三类进化（Skill/CLAUDE.md/Rule）写入，使 Claude Code 能从对话中自动学习。

## 触发方式

- **自动通知**：SessionStart hook 检测到待审查标记时通知用户
- **手动触发**：`/claude-evol` — 立即执行进化审查
- **自动模式**：`/claude-evol auto` — 切换自动写入模式（跳过用户确认）

## 元数据

- **调用方**：用户 `/claude-evol` 命令或 SessionStart hook 通知
- **被调用对象**：`agents/claude-evol-reviewer.md`、`scripts/state-manager.py`、`skills/`、`.claude/CLAUDE.md`、`.claude/rule/`
- **输入**：当前会话对话路径或手动输入的审查范围
- **输出**：更新后的 skills/、CLAUDE.md 或 .claude/rule/ 文件
- **在主流程中的位置**：主编排节点，连接 hook 检测和审查 Agent

## 主流程

### 1. 读取当前状态

执行 state-manager.py 获取当前计数器状态：

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-state
```

检查是否有待审查标记：

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-pending
```

### 2. 启动审查 Agent

使用 Fork 模式启动审查 Agent（继承当前上下文），传入对话记录：

```
Fork agent: claude-evol-reviewer
Input: 当前会话 transcript 路径或摘要
Task: 分析对话，执行三类进化判断（Skill/CLAUDE.md/Rule）
Output: 结构化 JSON 建议列表
```

审查 Agent 配置在 `agents/claude-evol-reviewer.md`，使用 haiku 模型（审查任务不需要最强模型）。

### 3. 展示审查结果

将审查 Agent 返回的 JSON 解析后展示给用户，按三类分组：
- Skill 建议（新建/更新技能）
- CLAUDE.md 建议（增量更新项目记忆）
- Rule 建议（新建/更新强制性规则）

### 4. 用户确认（默认模式）

展示每类建议的数量和摘要。非 auto 模式下，逐类询问用户确认：

```
发现 2 个 Skill 建议、1 个 CLAUDE.md 更新、0 个 Rule 建议。
是否应用 Skill 建议？[y/n]
是否应用 CLAUDE.md 更新？[y/n]
```

### 5. 写入文件

用户确认后，按建议写入对应文件：

- **Skill 建议**：写入 `.claude/skills/<skill-name>/SKILL.md`，新建或 patch 已有技能
- **CLAUDE.md 建议**：增量更新 `.claude/CLAUDE.md`，使用 patch 模式，不覆盖无关内容
- **Rule 建议**：写入 `.claude/rule/<constraint-name>.md`，每个约束独立文件

### 6. 重置状态

写入完成后重置计数器：

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py reset-all
```

## 自动模式

`/claude-evol auto` 切换自动模式状态。自动模式下，审查 Agent 的建议直接写入文件，无需用户逐类确认。

```bash
# 切换自动模式（在状态文件中标记）
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-state
# 读取 auto_mode 值，取反后写入
```

自动模式适合在信任度高的项目中持续运行，但建议首次使用时保持手动模式以建立信任。

## 后台自动触发流程

Hook 在后台持续工作，不需要手动调用：

```
PostToolUse Hook ─→ increment _iters_since_review
     ↓
Stop Hook ─→ check-all --set-flag（达标写入标记文件）
     ↓
SessionStart Hook ─→ get-pending（检测标记，通知用户）
     ↓
用户看到通知 → /claude-evol 手动触发或忽略
     ↓
审查完成 → reset-all
```

## 状态文件结构

`.claude/evol_state.json`：

```json
{
  "version": "1.0.0",
  "counters": {
    "_iters_since_review": 15
  },
  "thresholds": {
    "_iters_since_review": 10
  },
  "pending_review": false,
  "auto_mode": false
}
```

## 标记文件

`.claude/evol_review_pending.flag` 存在即表示有待审查标记，SessionStart hook 检测此文件后通知用户。

## 调试

查看完整状态：

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-state
```

手动重置：

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py reset-all
```

检查特定计数器是否达标：

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py check-threshold _iters_since_review 10
```
