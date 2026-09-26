#!/usr/bin/env python3
"""Local Ollama tool-calling agent for the Jarvis voice assistant."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


HOME = Path.home()
PROJECT = HOME / "Jarvis"
MASKS = PROJECT / "Masks"
CAMERA = HOME / ".local" / "bin" / "jarvis-camera"
DATA = PROJECT / "data"
HISTORY = DATA / "conversation_history.json"
OLLAMA_URL = os.environ.get("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.environ.get("JARVIS_AI_MODEL", "qwen3.5:2b")
SPEAKER = os.environ.get("JARVIS_SPEAKER", "Unknown")
DEBUG = os.environ.get("JARVIS_AI_DEBUG", "0") == "1"
MAX_HISTORY_MESSAGES = 8
MAX_TOOL_ROUNDS = 3


def debug(message: str) -> None:
    if DEBUG:
        print(f"AI debug: {message}", file=sys.stderr, flush=True)


def run(command: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def get_volume() -> str:
    """Read the default PipeWire/PulseAudio sink's volume and mute state."""
    result = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=5)
    if result.returncode != 0:
        return f"I could not read the speaker volume: {result.stderr.strip() or 'unknown audio error'}."

    match = re.search(r"/\s*(\d+)%", result.stdout)
    if match is None:
        return "I could not understand the current speaker volume."

    mute = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=5)
    muted = mute.returncode == 0 and "yes" in mute.stdout.lower()
    volume = int(match.group(1))
    if muted:
        return f"The speaker is muted. Its stored volume is {volume} percent."
    return f"The current speaker volume is {volume} percent."


def set_volume(percent: int) -> str:
    """Set the default sink volume, with a conservative voice-command limit."""
    try:
        volume = max(0, min(int(percent), 200))
    except (TypeError, ValueError):
        return "The volume must be a number between zero and two hundred."

    result = run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume}%"], timeout=5)
    if result.returncode != 0:
        return f"I could not set the speaker volume: {result.stderr.strip() or 'unknown audio error'}."
    return f"Volume set to {volume} percent."


def change_volume(amount: int) -> str:
    """Raise or lower the default sink by at most 20 percentage points."""
    try:
        change = max(-20, min(int(amount), 20))
    except (TypeError, ValueError):
        return "The volume change must be a number."

    if change == 0:
        return get_volume()
    adjustment = f"+{change}%" if change > 0 else f"{change}%"
    result = run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", adjustment], timeout=5)
    if result.returncode != 0:
        return f"I could not change the speaker volume: {result.stderr.strip() or 'unknown audio error'}."
    return get_volume()


def set_mute(muted: bool) -> str:
    """Set the default sink's mute state explicitly."""
    if not isinstance(muted, bool):
        return "The mute setting must be true or false."
    result = run(
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"],
        timeout=5,
    )
    if result.returncode != 0:
        return f"I could not change the speaker mute setting: {result.stderr.strip() or 'unknown audio error'}."
    return "The speaker is now muted." if muted else "The speaker is now unmuted."


def get_system_status() -> str:
    """Check whether Jarvis's core user services and Ollama are running."""
    names = ("jarvis-wake.service", "jarvis-sam3.service", "jarvis-stream.service")
    states: list[str] = []
    for name in names:
        result = run(["systemctl", "--user", "is-active", name], timeout=5)
        states.append(f"{name.removesuffix('.service')} is {result.stdout.strip() or 'unknown'}")

    try:
        request = urllib.request.Request("http://127.0.0.1:11434/api/version")
        with urllib.request.urlopen(request, timeout=3) as response:
            ollama = json.loads(response.read().decode("utf-8"))
        states.append(f"local AI is online using Ollama {ollama.get('version', 'unknown')}")
    except (OSError, ValueError):
        states.append("local AI status could not be confirmed")
    return "; ".join(states) + "."


def get_local_time() -> str:
    """Return the Ubuntu machine's current local date and time."""
    now = datetime.now().astimezone()
    return now.strftime("It is %I:%M %p on %A, %B %-d, %Y, in timezone %Z.").replace(" 0", " ")


def latest_manifest() -> tuple[Path, dict[str, Any]] | None:
    latest = MASKS / "latest"
    manifest_path = latest / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return latest.resolve(), json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def describe_latest_scene() -> str:
    """Describe object detections from the newest completed SAM3 analysis."""
    loaded = latest_manifest()
    if loaded is None:
        return "No completed SAM3 analysis is available."
    run_folder, manifest = loaded
    counts = Counter(
        item.get("prompt", "object").replace("_", " ")
        for item in manifest.get("detections", [])
    )
    if counts:
        detected = ", ".join(f"{count} {label}" for label, count in sorted(counts.items()))
    else:
        detected = "none of the configured object types"
    return (
        f"The latest analysis is {run_folder.name}. It detected {detected}. "
        f"It was processed at {manifest.get('processed_at', 'an unknown time')}."
    )


def list_recent_analyses(limit: int = 3) -> str:
    """List a small number of recently completed SAM3 analysis runs."""
    try:
        requested = max(1, min(int(limit), 5))
    except (TypeError, ValueError):
        requested = 3
    runs_root = MASKS / "runs"
    manifests = sorted(runs_root.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not manifests:
        return "No completed analysis history is available."

    summaries: list[str] = []
    for path in manifests[:requested]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        counts = Counter(item.get("prompt", "object") for item in manifest.get("detections", []))
        objects = ", ".join(f"{count} {name}" for name, count in sorted(counts.items())) or "no configured objects"
        summaries.append(f"{path.parent.name}: {objects}")
    return "; ".join(summaries) if summaries else "No readable analysis history is available."


def take_picture() -> str:
    """Capture one room image and place it in Footage for SAM3 processing."""
    if not CAMERA.is_file():
        return "The camera command is missing."
    try:
        result = run([str(CAMERA)], timeout=25)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"The camera did not respond: {error}."
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown camera error"
        return f"The picture was not captured: {detail}."
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    path = lines[-1] if lines else "the Footage directory"
    return f"Picture captured at {path}. SAM3 will process it asynchronously."


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_local_time",
            "description": "Get the current local date, time, and timezone from the Ubuntu Jarvis machine.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Check whether the Jarvis wake listener, SAM3 watcher, room stream, and local AI are online.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_latest_scene",
            "description": "Read and summarize the newest completed SAM3 object-detection manifest.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_analyses",
            "description": "List recent completed SAM3 analyses and their object counts.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 5}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_picture",
            "description": "Capture a new room photograph when the user explicitly requests a photo or image.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_volume",
            "description": "Read the current volume and mute state of the default speaker.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set the default speaker volume to a specific percentage from zero through eighty.",
            "parameters": {
                "type": "object",
                "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 80}},
                "required": ["percent"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_volume",
            "description": "Raise or lower speaker volume relatively. Positive raises it and negative lowers it.",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "integer", "minimum": -20, "maximum": 20}},
                "required": ["amount"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mute",
            "description": "Explicitly mute or unmute the default speaker.",
            "parameters": {
                "type": "object",
                "properties": {"muted": {"type": "boolean"}},
                "required": ["muted"],
                "additionalProperties": False,
            },
        },
    },
]

AVAILABLE_TOOLS: dict[str, Callable[..., str]] = {
    "get_local_time": get_local_time,
    "get_system_status": get_system_status,
    "describe_latest_scene": describe_latest_scene,
    "list_recent_analyses": list_recent_analyses,
    "take_picture": take_picture,
    "get_volume": get_volume,
    "set_volume": set_volume,
    "change_volume": change_volume,
    "set_mute": set_mute,
}


def load_history() -> list[dict[str, str]]:
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        {"role": item["role"], "content": item["content"]}
        for item in data[-MAX_HISTORY_MESSAGES:]
        if isinstance(item, dict)
        and item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
    ]


def save_history(messages: list[dict[str, str]]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = messages[-MAX_HISTORY_MESSAGES:]
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="jarvis-history-", suffix=".json", dir=DATA, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(HISTORY)


def call_ollama(messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 160},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=150) as response:
        result = json.loads(response.read().decode("utf-8"))
    message = result.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama returned no assistant message")
    return message


def execute_tool(call: dict[str, Any]) -> tuple[str, str]:
    function = call.get("function", {})
    name = function.get("name", "")
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}

    tool = AVAILABLE_TOOLS.get(name)
    if tool is None:
        return name or "unknown", "That tool is not approved for Jarvis."
    debug(f"calling {name} with {arguments}")
    try:
        return name, tool(**arguments)
    except (OSError, TypeError, ValueError, subprocess.TimeoutExpired) as error:
        return name, f"The tool failed safely: {error}."


def ask(user_text: str) -> str:
    history = load_history()
    speaker_context = SPEAKER if SPEAKER != "Unknown" else "an unidentified speaker"
    system = (
        "You are Jarvis, a concise household voice and vision assistant running locally on Ubuntu. "
        "Your response will be spoken aloud, so use plain text, no Markdown, no lists unless necessary, "
        "and normally one to three short sentences. Be calm, capable, and lightly witty without impersonating "
        "a real person. Use the provided tools when current system, camera, or vision data is required. "
        "Never claim an action succeeded unless its tool result confirms success. You have no shell access and "
        "must not invent tools. You do not directly watch or analyze the live video stream. The stream is a "
        "separate remote-viewing service, while SAM3 analyzes individual saved photographs. Only describe current "
        "vision results after using a vision tool. Your language model interprets requests and selects approved "
        "tools; it does not replace Whisper, SAM3, or the safety checks. The current speaker is "
        + speaker_context
        + "."
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history]
    messages.append({"role": "user", "content": user_text})

    answer = ""
    for _ in range(MAX_TOOL_ROUNDS):
        assistant = call_ollama(messages)
        messages.append(assistant)
        calls = assistant.get("tool_calls") or []
        if not calls:
            answer = str(assistant.get("content", "")).strip()
            break
        for call in calls:
            if not isinstance(call, dict):
                continue
            name, result = execute_tool(call)
            messages.append({"role": "tool", "tool_name": name, "content": result})

    if not answer:
        answer = "I could not complete that request safely."
    save_history([*history, {"role": "user", "content": user_text}, {"role": "assistant", "content": answer}])
    return answer


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: jarvis-ai <request>", file=sys.stderr)
        return 2
    try:
        print(ask(" ".join(sys.argv[1:])))
        return 0
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as error:
        print(f"Jarvis AI unavailable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
