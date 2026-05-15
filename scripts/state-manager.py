#!/usr/bin/env python3
"""
claude-evol state-manager.py — 纯标准库状态管理器

- 调用方：hooks (PostToolUse/Stop/SessionStart) 和 skills/claude-evol/SKILL.md
- 被调用对象：.claude/evol_state.json, .claude/evol_review_pending.flag
- 输入：子命令 + 参数（通过 CLI args）
- 输出：stdout JSON 或纯文本值
- 在主流程中的位置：状态读写层，被 hook 和 skill 共同依赖

安装位置：.claude/scripts/evol/state-manager.py
状态文件：.claude/evol_state.json
标记文件：.claude/evol_review_pending.flag
"""

import json
import os
import sys
import glob as glob_mod
import argparse
from pathlib import Path

# ---------- 配置 ----------

DEFAULT_THRESHOLDS = {
    "_iters_since_review": 10,
}

DEFAULT_STATE = {
    "version": "1.0.0",
    "counters": {},
    "thresholds": {},
    "pending_review": False,
    "auto_mode": False,
}


def find_project_root() -> Path:
    """查找项目根目录（包含 .claude/ 的目录）"""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        p = Path(env_root)
        if (p / ".claude").is_dir():
            return p

    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".claude").is_dir():
            return parent

    return cwd


def get_state_path() -> Path:
    return find_project_root() / ".claude" / "evol_state.json"


def get_flag_path() -> Path:
    return find_project_root() / ".claude" / "evol_review_pending.flag"


def load_state() -> dict:
    path = get_state_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            # 确保必要字段存在
            state.setdefault("counters", {})
            state.setdefault("thresholds", {})
            state.setdefault("pending_review", False)
            state.setdefault("auto_mode", False)
            return state
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_STATE)


def save_state(state: dict):
    path = get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ---------- 子命令 ----------

def cmd_increment(counter_name: str):
    state = load_state()
    state["counters"][counter_name] = state["counters"].get(counter_name, 0) + 1
    # PostToolUse 在活跃会话中运行，能拿到 CLAUDE_CODE_SESSION_ID
    # 缓存下来供 Stop hook 使用（Stop hook 子进程拿不到此环境变量）
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid:
        state["_cached_session_id"] = sid
    save_state(state)
    print(state["counters"][counter_name])


def cmd_get(counter_name: str):
    state = load_state()
    val = state["counters"].get(counter_name, 0)
    print(val)


def cmd_get_state():
    state = load_state()
    print(json.dumps(state, indent=2, ensure_ascii=False))


def cmd_reset(counter_name: str):
    state = load_state()
    state["counters"][counter_name] = 0
    save_state(state)
    print(f"ok: {counter_name} reset to 0")


def cmd_reset_all():
    state = load_state()
    state["counters"] = {}
    state["pending_review"] = False
    state.pop("_cached_session_id", None)
    save_state(state)
    # 同时删除标记文件
    flag_path = get_flag_path()
    if flag_path.exists():
        flag_path.unlink()
    print("ok: all counters and flags reset")


def cmd_check_threshold(counter_name: str, threshold: int):
    state = load_state()
    current = state["counters"].get(counter_name, 0)
    result = current >= threshold
    print(json.dumps({
        "counter": counter_name,
        "current": current,
        "threshold": threshold,
        "reached": result,
    }))


def cmd_check_all(set_flag: bool = False):
    state = load_state()
    thresholds = {**DEFAULT_THRESHOLDS, **state.get("thresholds", {})}
    results = {}
    any_reached = False

    for counter_name, threshold in thresholds.items():
        current = state["counters"].get(counter_name, 0)
        reached = current >= threshold
        results[counter_name] = {
            "current": current,
            "threshold": threshold,
            "reached": reached,
        }
        if reached:
            any_reached = True

    if set_flag and any_reached:
        state["pending_review"] = True
        save_state(state)
        # Stop hook 子进程拿不到 CLAUDE_CODE_SESSION_ID，从 state 缓存读取
        session_id = state.get("_cached_session_id", "")
        flag_path = get_flag_path()
        flag_path.write_text(
            json.dumps({
                "timestamp": str(Path.cwd()),
                "session_id": session_id,
                "triggers": {
                    k: v for k, v in results.items() if v["reached"]
                }
            }, indent=2)
        )
        print(json.dumps({"flag_set": True, "triggers": results}))
    else:
        print(json.dumps({"flag_set": False, "triggers": results}))


def cmd_get_pending():
    flag_path = get_flag_path()
    if flag_path.exists():
        try:
            content = flag_path.read_text()
            detail = json.loads(content)
            triggers = detail.get("triggers", {})
            trigger_info = ", ".join(
                f"{k}: {v.get('current', '?')}/{v.get('threshold', '?')}"
                for k, v in triggers.items()
            )
            # ANSI 彩色输出，SessionStart 时不会被其他噪音淹没
            bold = "\033[1m"
            red = "\033[91m"
            yellow = "\033[93m"
            reset = "\033[0m"
            print(f"{bold}{red}╔══════════════════════════════════════╗{reset}")
            print(f"{bold}{red}║  🧬 claude-evol: 进化建议待审查        ║{reset}")
            print(f"{bold}{red}║  触发: {trigger_info:<30}║{reset}")
            print(f"{bold}{red}║  输入 {yellow}/claude-evol{red} 开始进化审查         ║{reset}")
            print(f"{bold}{red}╚══════════════════════════════════════╝{reset}")
            # 同时输出机器可读 JSON 到 stderr 供日志
            print(json.dumps({"pending": True, "detail": detail}), file=sys.stderr)
        except (json.JSONDecodeError, IOError):
            print(json.dumps({"pending": True, "detail": {}}))
    else:
        # 无待审查时静默，不污染 SessionStart 输出
        pass


def cmd_get_transcript():
    """读取 flag 文件中的 session_id，找到 transcript 文件路径"""
    flag_path = get_flag_path()
    if not flag_path.exists():
        print(json.dumps({"found": False, "path": ""}))
        return
    try:
        flag_data = json.loads(flag_path.read_text())
        session_id = flag_data.get("session_id", "")
        if not session_id:
            print(json.dumps({"found": False, "path": "", "error": "no session_id in flag"}))
            return
        pattern = str(Path.home() / ".claude" / "projects" / "*" / f"{session_id}.jsonl")
        matches = glob_mod.glob(pattern)
        if matches:
            print(json.dumps({"found": True, "path": matches[0]}))
        else:
            print(json.dumps({"found": False, "path": "", "error": f"no transcript for {session_id}"}))
    except (json.JSONDecodeError, IOError) as e:
        print(json.dumps({"found": False, "path": "", "error": str(e)}))


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(
        description="claude-evol state manager"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # increment <counter_name>
    p = subparsers.add_parser("increment")
    p.add_argument("counter_name")

    # get <counter_name>
    p = subparsers.add_parser("get")
    p.add_argument("counter_name")

    # get-state
    subparsers.add_parser("get-state")

    # reset <counter_name>
    p = subparsers.add_parser("reset")
    p.add_argument("counter_name")

    # reset-all
    subparsers.add_parser("reset-all")

    # check-threshold <counter_name> <threshold>
    p = subparsers.add_parser("check-threshold")
    p.add_argument("counter_name")
    p.add_argument("threshold", type=int)

    # check-all [--set-flag]
    p = subparsers.add_parser("check-all")
    p.add_argument("--set-flag", action="store_true")

    # get-pending
    subparsers.add_parser("get-pending")

    # get-transcript
    subparsers.add_parser("get-transcript")

    args = parser.parse_args()

    if args.command == "increment":
        cmd_increment(args.counter_name)
    elif args.command == "get":
        cmd_get(args.counter_name)
    elif args.command == "get-state":
        cmd_get_state()
    elif args.command == "reset":
        cmd_reset(args.counter_name)
    elif args.command == "reset-all":
        cmd_reset_all()
    elif args.command == "check-threshold":
        cmd_check_threshold(args.counter_name, args.threshold)
    elif args.command == "check-all":
        cmd_check_all(set_flag=args.set_flag)
    elif args.command == "get-pending":
        cmd_get_pending()
    elif args.command == "get-transcript":
        cmd_get_transcript()


if __name__ == "__main__":
    main()
