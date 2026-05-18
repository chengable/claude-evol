#!/usr/bin/env python3
"""
claude-evol state-manager.py — 纯标准库状态管理器

- 调用方：hooks (PostToolUse/Stop/SessionStart) 和 skills/claude-evol/SKILL.md
- 被调用对象：.claude/.claude-evol/evol_state.json, .claude/.claude-evol/evol_review_pending.flag
- 输入：子命令 + 参数（通过 CLI args）
- 输出：stdout JSON 或纯文本值
- 在主流程中的位置：状态读写层，被 hook 和 skill 共同依赖

安装位置：.claude/scripts/evol/state-manager.py
状态文件：.claude/.claude-evol/evol_state.json
标记文件：.claude/.claude-evol/evol_review_pending.flag
"""

import json
import os
import sys
import glob as glob_mod
import argparse
from pathlib import Path

# ---------- 配置 ----------

DEFAULT_THRESHOLDS = {
    "_iters_since_review": 20,
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
    return find_project_root() / ".claude" / ".claude-evol" / "evol_state.json"


def get_flag_path() -> Path:
    return find_project_root() / ".claude" / ".claude-evol" / "evol_review_pending.flag"


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

def read_hook_stdin() -> dict | None:
    """读取 hook 通过 stdin 传入的 JSON，非 hook 调用时返回 None"""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, IOError):
        return None


def cmd_increment(counter_name: str = None):
    hook_input = read_hook_stdin()
    session_id = hook_input.get("session_id", "unknown") if hook_input else "unknown"
    state = load_state()
    key = f"session:{session_id}"
    state["counters"][key] = state["counters"].get(key, 0) + 1
    save_state(state)


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


def cmd_toggle_auto():
    state = load_state()
    current = state.get("auto_mode", False)
    state["auto_mode"] = not current
    save_state(state)
    new_val = state["auto_mode"]
    status = "开启" if new_val else "关闭"
    print(f"auto_mode → {status}")


def cmd_reset_all():
    state = load_state()
    state["counters"] = {}
    state["pending_review"] = False
    save_state(state)
    # 删除标记文件
    flag_path = get_flag_path()
    if flag_path.exists():
        flag_path.unlink()
    print("ok: all counters and flags reset")


def cmd_check_threshold(counter_name: str, threshold: int):
    hook_input = read_hook_stdin()
    session_id = hook_input.get("session_id", "unknown") if hook_input else "unknown"
    state = load_state()
    key = f"session:{session_id}"
    current = state["counters"].get(key, 0)
    result = current >= threshold
    print(json.dumps({
        "session_id": session_id,
        "current": current,
        "threshold": threshold,
        "reached": result,
    }))


def cmd_check_all(set_flag: bool = False):
    state = load_state()
    hook_input = read_hook_stdin()
    session_id = hook_input.get("session_id", "") if hook_input else ""
    transcript_path = hook_input.get("transcript_path", "") if hook_input else ""

    key = f"session:{session_id}"
    current = state["counters"].get(key, 0)
    threshold = DEFAULT_THRESHOLDS.get("_iters_since_review", 20)
    reached = current >= threshold

    if set_flag:
        flag_path = get_flag_path()
        queue = []
        if flag_path.exists():
            try:
                queue = json.loads(flag_path.read_text())
                if not isinstance(queue, list):
                    queue = []
            except (json.JSONDecodeError, IOError):
                queue = []

        if reached:
            existing = next((e for e in queue if e.get("session_id") == session_id), None)
            if existing:
                existing["count"] = current
                existing["transcript_path"] = transcript_path
            else:
                queue.append({
                    "session_id": session_id,
                    "transcript_path": transcript_path,
                    "count": current,
                })
            flag_path.parent.mkdir(parents=True, exist_ok=True)
            flag_path.write_text(json.dumps(queue, indent=2, ensure_ascii=False))

        state["pending_review"] = len(queue) > 0
        save_state(state)

        if queue:
            total_pending = len(queue)
            bold = "\033[1m"
            yellow = "\033[93m"
            reset = "\033[0m"

            lines = [f"{bold}{yellow}🧬 claude-evol: 以下 {total_pending} 个会话已达审查阈值（≥{threshold} 次调用）：{reset}"]
            for i, entry in enumerate(queue):
                sid = entry.get("session_id", "?")[:8]
                cnt = entry.get("count", "?")
                lines.append(f"{bold}{yellow}  [{i+1}] {sid}... — {cnt} 次调用{reset}")
            lines.append(f"{bold}{yellow}运行 /claude-evol 将审查以上全部会话并生成进化建议{reset}")

            reminder = "\n".join(lines)

            print(json.dumps({
                "continue": True,
                "suppressOutput": False,
                "systemMessage": reminder,
                "flag_set": reached,
                "session_count": current,
                "pending_total": total_pending,
            }))
        else:
            print(json.dumps({"flag_set": False, "session_count": current, "pending_total": 0}))
    else:
        print(json.dumps({"flag_set": False, "session_count": current}))


def cmd_get_pending():
    flag_path = get_flag_path()
    if not flag_path.exists():
        return
    try:
        queue = json.loads(flag_path.read_text())
        if not isinstance(queue, list) or not queue:
            return
        # 显示待审查摘要
        bold = "\033[1m"
        red = "\033[91m"
        yellow = "\033[93m"
        reset = "\033[0m"
        total = len(queue)
        total_calls = sum(e.get("count", 0) for e in queue)
        print(f"{bold}{red}╔══════════════════════════════════════╗{reset}")
        print(f"{bold}{red}║  🧬 claude-evol: {total} 个待审查会话 ({total_calls} 次调用)    ║{reset}")
        for i, entry in enumerate(queue):
            sid = entry.get("session_id", "?")[:8]
            count = entry.get("count", "?")
            print(f"{bold}{red}║  [{i+1}] {sid}... — {count} 次调用{'':<20}║{reset}")
        print(f"{bold}{red}║  输入 {yellow}/claude-evol{red} 开始进化审查         ║{reset}")
        print(f"{bold}{red}╚══════════════════════════════════════╝{reset}")
        print(json.dumps({"pending": True, "queue": queue}))
    except (json.JSONDecodeError, IOError):
        pass


def cmd_get_transcript():
    """读取 flag 队列，返回所有待审查 transcript"""
    flag_path = get_flag_path()
    if not flag_path.exists():
        print(json.dumps({"found": False, "transcripts": []}))
        return
    try:
        queue = json.loads(flag_path.read_text())
        if not isinstance(queue, list):
            print(json.dumps({"found": False, "transcripts": []}))
            return
        transcripts = []
        for entry in queue:
            tp = entry.get("transcript_path", "")
            if tp and Path(tp).exists():
                transcripts.append({"session_id": entry.get("session_id", ""),
                                     "path": tp, "count": entry.get("count", 0)})
        print(json.dumps({"found": len(transcripts) > 0, "transcripts": transcripts},
                         ensure_ascii=False))
    except (json.JSONDecodeError, IOError) as e:
        print(json.dumps({"found": False, "transcripts": [], "error": str(e)}))


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(
        description="claude-evol state manager"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # increment [counter_name]  (counter_name 可选，session_id 从 stdin 读取)
    p = subparsers.add_parser("increment")
    p.add_argument("counter_name", nargs="?")

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

    # toggle-auto
    subparsers.add_parser("toggle-auto")

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
    elif args.command == "toggle-auto":
        cmd_toggle_auto()
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
