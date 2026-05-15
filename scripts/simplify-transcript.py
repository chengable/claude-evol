#!/usr/bin/env python3
"""Simplify Claude Code transcript JSONL for evolution review.

Adopts Hermes-style compression:
  - Tool output → one-line summary: [tool:Name] ran 'cmd' -> exit 0, 47 lines
  - Duplicate tool outputs → [Duplicate tool output]
  - Tool call params >500 chars → truncated
  - Images/multimodal → [screenshot] placeholder
  - Drop: attachment, system, file-history-snapshot, metadata types
  - Drop: assistant thinking blocks
"""

import json
import sys
import os
import hashlib

KEEP_TYPES = {"user", "assistant"}
TOOL_PARAM_MAX = 500
INPUT_SUMMARY_MAX = 80


def _fingerprint(tool_name, tool_input):
    """Hash (tool_name, input) for duplicate detection."""
    raw = json.dumps({"name": tool_name, "input": tool_input}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _summarize_input(tool_input):
    """Extract a short human-readable input summary."""
    if not isinstance(tool_input, dict) or not tool_input:
        return ""
    # Handle truncated placeholder from _truncate_tool_params
    if "_preview" in tool_input:
        preview = tool_input["_preview"]
        if len(preview) > INPUT_SUMMARY_MAX:
            return preview[:INPUT_SUMMARY_MAX] + "..."
        return preview
    # Bash tool: use command or description
    if "command" in tool_input:
        cmd = tool_input["command"]
        first_line = cmd.split("\n")[0].strip()
        if len(first_line) > INPUT_SUMMARY_MAX:
            return first_line[:INPUT_SUMMARY_MAX] + "..."
        return first_line
    if "description" in tool_input:
        desc = tool_input["description"]
        if len(desc) > INPUT_SUMMARY_MAX:
            return desc[:INPUT_SUMMARY_MAX] + "..."
        return desc
    # Generic: use first value that's a short string
    for v in tool_input.values():
        if isinstance(v, str) and 3 < len(v) <= INPUT_SUMMARY_MAX:
            return v
    return ""


def _count_lines(text):
    """Count non-empty lines."""
    if not text:
        return 0
    return len([l for l in text.split("\n") if l.strip()])


def _tool_result_summary(tool_name, tool_input, tool_result):
    """Generate one-line Hermes-style summary for a tool result."""
    if not isinstance(tool_result, dict):
        return tool_result

    stdout = tool_result.get("stdout", "") or ""
    stderr = tool_result.get("stderr", "") or ""
    interrupted = tool_result.get("interrupted", False)
    persisted = tool_result.get("persistedOutputPath", "")

    input_summary = _summarize_input(tool_input)
    total_lines = _count_lines(stdout) + _count_lines(stderr)

    if interrupted:
        status = "interrupted"
    elif stderr.strip() and not stdout.strip():
        status = "stderr"
    else:
        status = "exit 0"

    cmd_part = f"'{input_summary}'" if input_summary else tool_name

    if persisted:
        fname = os.path.basename(persisted)
        return f"[tool:{tool_name}] ran {cmd_part} -> {status}, {total_lines} lines, persisted to {fname}"

    return f"[tool:{tool_name}] ran {cmd_part} -> {status}, {total_lines} lines"


def _extract_tool_use_ids(content_blocks):
    """Extract tool_use_id(s) from tool_result blocks in user content."""
    if not isinstance(content_blocks, list):
        return []
    return [b.get("tool_use_id", "") for b in content_blocks if b.get("type") == "tool_result" and b.get("tool_use_id")]


def _register_tool_uses(content_blocks, known_tools):
    """Register tool_use blocks from assistant content into known_tools dict."""
    if not isinstance(content_blocks, list):
        return
    for b in content_blocks:
        if b.get("type") == "tool_use":
            tid = b.get("id", "")
            if tid:
                known_tools[tid] = {"name": b.get("name", ""), "input": b.get("input", {})}


def _truncate_tool_params(content_blocks):
    """Truncate tool_use input params >500 chars."""
    if not isinstance(content_blocks, list):
        return content_blocks
    result = []
    for b in content_blocks:
        if b.get("type") == "tool_use" and "input" in b:
            inp = json.dumps(b["input"], ensure_ascii=False)
            if len(inp) > TOOL_PARAM_MAX:
                truncated = dict(b)
                truncated["input"] = {"_truncated": f"original {len(inp)} chars", "_preview": inp[:TOOL_PARAM_MAX]}
                result.append(truncated)
            else:
                result.append(b)
        else:
            result.append(b)
    return result


def _strip_images(content_blocks):
    """Replace image/multimodal blocks with [screenshot] placeholder."""
    if not isinstance(content_blocks, list):
        return content_blocks
    result = []
    for b in content_blocks:
        t = b.get("type", "")
        if t in ("image", "image_url", "input_image"):
            result.append({"type": "text", "text": "[screenshot]"})
        elif t == "tool_result":
            # Check if content contains base64 images
            b2 = dict(b)
            if isinstance(b2.get("content"), str) and len(b2["content"]) > 10000:
                b2["content"] = "[screenshot removed to save context]"
            result.append(b2)
        elif t == "tool_use" and isinstance(b.get("input"), dict):
            # Check for image data in tool input
            b2 = dict(b)
            for key in list(b2["input"].keys()):
                val = b2["input"][key]
                if isinstance(val, str) and len(val) > 10000:
                    b2["input"][key] = "[base64 data removed]"
            result.append(b2)
        else:
            result.append(b)
    return result


def simplify_transcript(input_path, output_path=None):
    """Process transcript, returning output lines list and stats."""

    seen_fingerprints = {}
    known_tools = {}  # tool_use_id -> {name, input}

    kept = 0
    dropped = 0
    dupes = 0
    lines_out = []

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = entry.get("type", "")
            if etype not in KEEP_TYPES:
                dropped += 1
                continue

            simplified = {}
            for key in ("type", "uuid", "timestamp", "sessionId"):
                if key in entry:
                    simplified[key] = entry[key]

            # --- Process message.content ---
            if "message" in entry and isinstance(entry["message"], dict):
                msg = entry["message"]
                simplified["message"] = {}
                if "role" in msg:
                    simplified["message"]["role"] = msg["role"]

                content = msg.get("content")
                if content is not None:
                    content = _strip_images(content)
                    content = _truncate_tool_params(content)
                    if isinstance(content, list):
                        content = [b for b in content if b.get("type") != "thinking"]
                    simplified["message"]["content"] = content

                    # Register tool_use from assistant entries for later lookup
                    if etype == "assistant":
                        _register_tool_uses(content, known_tools)

            # --- Process tool result (user entries only) ---
            if etype == "user" and "toolUseResult" in entry and entry["toolUseResult"] is not None:
                # Look up tool info from previously registered tool_uses
                tool_use_ids = _extract_tool_use_ids(entry.get("message", {}).get("content", []))
                matched = None
                for tid in tool_use_ids:
                    if tid in known_tools:
                        matched = known_tools[tid]
                        break

                if matched:
                    tu_name = matched["name"]
                    tu_input = matched["input"]
                    fp = _fingerprint(tu_name, tu_input)
                    if fp in seen_fingerprints:
                        simplified["toolUseResult"] = {"_summary": "[Duplicate tool output]"}
                        dupes += 1
                    else:
                        seen_fingerprints[fp] = True
                        summary = _tool_result_summary(tu_name, tu_input, entry["toolUseResult"])
                        simplified["toolUseResult"] = {"_summary": summary}
                else:
                    summary = _tool_result_summary("unknown", {}, entry["toolUseResult"])
                    simplified["toolUseResult"] = {"_summary": summary}

            lines_out.append(json.dumps(simplified, ensure_ascii=False))
            kept += 1

    output = "\n".join(lines_out) + "\n"
    return output, kept, dropped, dupes


def _derive_output_path(input_path):
    """Generate output path: same dir, simple_ prefix on filename."""
    dirname = os.path.dirname(input_path)
    basename = os.path.basename(input_path)
    return os.path.join(dirname, f"simple_{basename}")


def main():
    if len(sys.argv) < 2:
        print("Usage: simplify-transcript.py <input.jsonl>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = _derive_output_path(input_path)

    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    input_size = os.path.getsize(input_path)
    output, kept, dropped, dupes = simplify_transcript(input_path, output_path)
    output_size = len(output.encode("utf-8"))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    reduction = (1 - output_size / input_size) * 100 if input_size > 0 else 0
    print(f"Input:  {input_path} ({input_size / 1024:.1f} KB, {kept + dropped} entries)", file=sys.stderr)
    print(f"Output: {output_path} ({output_size / 1024:.1f} KB, {kept} kept, {dropped} dropped, {dupes} duplicates)", file=sys.stderr)
    print(f"Reduction: {reduction:.0f}%", file=sys.stderr)


if __name__ == "__main__":
    main()
