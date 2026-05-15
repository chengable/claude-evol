# claude-evol — Claude Code 自主进化插件

将 Hermes 自主进化能力移植到 Claude Code。自动检测对话中的重复模式、错误经验和领域知识，生成三类进化建议（Skill/CLAUDE.md/Rule），让 Claude Code 越用越聪明。

## 功能

- **自动检测**：Hook 后台自动计数，达到阈值后下次会话通知用户审查
- **三类进化**：审查 Agent 自动判断信息属于 Skill（怎么做）、CLAUDE.md（记住什么）还是 Rule（必须/禁止）
- **手动触发**：`/claude-evol` 命令随时启动进化审查
- **自动模式**：`/claude-evol auto` 切换自动写入，跳过用户确认
- **安全保守**：默认用户确认模式 + 负面清单 + 增量更新

## 目录结构

```
claude-evol/
├── .claude-plugin/
│   └── plugin.json                    # 插件清单
├── marketplace.json                   # 插件市场元数据
├── skills/
│   └── claude-evol/
│       └── SKILL.md                   # 主编排 Skill（/claude-evol 命令）
├── agents/
│   └── claude-evol-reviewer.md        # 审查 Agent（三类进化判断）
├── hooks/
│   └── hooks.json                     # PostToolUse/Stop/SessionStart Hook
├── scripts/
│   ├── state-manager.py               # 状态管理器（纯标准库）
│   └── requirements.txt               # Python >= 3.8
└── README.md
```

## 安装

### 添加插件市场

```bash
/plugin marketplace add chengable/claude-evol
```

### 安装插件

```bash
/plugin install claude-evol
```

安装后 Hook 自动生效，无需额外配置。使用 `/claude-evol` 手动触发进化审查。

## 使用方式

### 手动触发

```
/claude-evol
```

立即启动进化审查。审查 Agent 分析当前会话，生成三类建议：
- **Skill 建议**：可复用的操作流程（新建 umbrella skill / patch 已有 skill）
- **CLAUDE.md 建议**：项目知识/用户经验（增量更新，不覆盖无关内容）
- **Rule 建议**：强制性约束（每个约束独立 .md 文件到 `.claude/rule/`）

### 自动模式

```
/claude-evol auto
```

切换自动写入模式。切换后审查建议直接写入文件，不再逐类确认。

### 自动触发流程

无需手动操作，Hook 在后台工作：

```
PostToolUse Hook → increment（每次工具调用 +1）
       ↓
Stop Hook → check-all --set-flag（达标写入标记）
       ↓
SessionStart Hook → get-pending（检测标记，通知用户）
       ↓
用户看到通知 → /claude-evol 或忽略
```

默认阈值：Skill 20 次工具调用，Memory 30 次。

## 三类进化判断逻辑

审查 Agent 将对话中发现的信息分为三类：

| 进化目标 | 本质 | 触发信号 |
|---------|------|---------|
| **Skill** | 怎么做 | 重复模式(≥3次)、错误→解决流程、工具组合、领域知识 |
| **CLAUDE.md** | 记住什么 | 用户纠正、项目事实、经验总结、正确/错误经验 |
| **.claude/rule/** | 必须/禁止 | 硬性约束、安全要求、代码规范、兼容性限制 |

```
对话中的信息
  ├─ 可复用的操作流程？       → Skill
  ├─ 关于项目/用户的记忆？    → CLAUDE.md
  └─ 强制性的约束/规则？     → .claude/rule/
```

## 组件链路

```
skills/claude-evol/SKILL.md（主编排）
  ├── [Fork] agents/claude-evol-reviewer.md（审查 Agent，haiku 模型）
  │     ├── 分析对话 → 三分类判断
  │     └── 输出：结构化 JSON 建议
  ├── [调用] scripts/state-manager.py（读写 evol_state.json）
  └── [写入] skills/、CLAUDE.md、.claude/rule/

hooks/hooks.json
  ├── PostToolUse → state-manager.py increment
  ├── Stop        → state-manager.py check-all --set-flag
  └── SessionStart → state-manager.py get-pending
```

## 发布与市场

`marketplace.json` 位于仓库根目录，供 Claude Code 插件市场自动发现：

```json
{
  "name": "claude-evol",
  "repository": "https://github.com/chengable/claude-evol.git",
  "category": "productivity",
  "keywords": ["evolution", "self-improvement", "skill", "memory", "hermes"]
}
```

发布新版本时更新 `version` 字段即可。

## 调试

```bash
# 查看完整状态
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get-state

# 手动重置
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py reset-all

# 检查特定计数器
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py get _iters_since_skill

# 检查阈值
python ${CLAUDE_PLUGIN_ROOT}/scripts/state-manager.py check-threshold _iters_since_skill 20
```

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Hook 性能影响 | state-manager.py 单文件 JSON 读写，<1ms |
| 上下文窗口溢出 | 审查 Agent 接收摘要而非完整对话 |
| 自说自话循环 | 负面清单 + 默认用户确认模式 |
| 三类进化判断不准 | 审查 prompt 明确给出分类标准和示例 |
| 跨项目状态污染 | 状态文件存储在项目 `.claude/` 下，天然隔离 |

## 卸载

```bash
/plugin disable claude-evol
/plugin uninstall claude-evol
/plugin marketplace remove claude-evol
```

## 许可

MIT
