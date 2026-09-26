#!/usr/bin/env python3
"""Small offline intent router for the Jarvis camera and voice system."""

from __future__ import annotations

import json
import re
import secrets
import math
import os
import subprocess
import sys
import tempfile
import wave
from collections import Counter
from datetime import datetime
from pathlib import Path


HOME = Path.home()
PROJECT = HOME / "Jarvis"
SPEAK = HOME / ".local" / "bin" / "jarvis-speak"
CAMERA = HOME / ".local" / "bin" / "jarvis-camera"
AI = PROJECT / "jarvis_ai.py"
MASKS = PROJECT / "Masks"
SPEAKER = os.environ.get("JARVIS_SPEAKER", "Unknown")

CANCEL_PATTERN = re.compile(
    r"\b(?:jarvis\s+(?:please\s+)?(?:stop|cancel|be\s+quiet|quiet|shut\s+up)"
    r"|cancel\s+(?:that|it|this)|never\s+mind|be\s+quiet)\b"
)


JOKES = (
    "Why did the computer get cold? It left its Windows open.",
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people: those who understand binary, and those who do not.",
    "My camera and I have a lot in common. We both need time to process things.",
)

MOTIVATION = (
    "Small progress is still progress. Keep building.",
    "You do not need the whole plan. You only need the next useful step.",
    "Systems become impressive one reliable feature at a time.",
    "Today is an excellent day to make the impossible slightly more operational.",
)


def run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def speak(message: str) -> None:
    print(f"Jarvis: {message}")
    try:
        result = run([str(SPEAK), message], timeout=120)
        if result.returncode:
            print(result.stderr.strip(), file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Speech error: {error}", file=sys.stderr)


def ask_ai(transcript: str) -> str | None:
    """Ask the local allowlisted AI agent, returning None for safe fallback."""
    if os.environ.get("JARVIS_AI_ENABLED", "1") == "0" or not AI.is_file():
        return None
    try:
        result = run([sys.executable, str(AI), transcript], timeout=170)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"AI error: {error}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(result.stderr.strip() or "Jarvis AI returned an error.", file=sys.stderr)
        return None
    response = result.stdout.strip()
    return response or None


def take_picture() -> None:
    speak("Taking a picture now.")
    try:
        result = run([str(CAMERA)], timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        speak("I could not reach the camera.")
        print(f"Camera error: {error}", file=sys.stderr)
        return

    if result.returncode == 0:
        path = result.stdout.strip().splitlines()[-1]
        print(f"Captured: {path}")
        speak("Picture captured. The vision system is processing it.")
    else:
        print(result.stderr.strip(), file=sys.stderr)
        speak("The camera did not complete the picture.")


def sound_alarm() -> None:
    """Play a short alternating alarm through the current PipeWire output."""
    speak("Warning. Alarm activated.")
    sample_rate = 44100
    duration_seconds = 4
    pulse_seconds = 0.25
    amplitude = 15000
    path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(prefix="jarvis-alarm-", suffix=".wav", delete=False) as handle:
            path = Path(handle.name)

        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            frames = bytearray()
            for index in range(sample_rate * duration_seconds):
                elapsed = index / sample_rate
                frequency = 880 if int(elapsed / pulse_seconds) % 2 == 0 else 660
                envelope = 1.0 if (elapsed % pulse_seconds) < pulse_seconds * 0.78 else 0.0
                sample = int(amplitude * envelope * math.sin(2 * math.pi * frequency * elapsed))
                frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
            audio.writeframes(frames)

        result = run(["pw-play", str(path)], timeout=10)
        if result.returncode:
            print(result.stderr.strip(), file=sys.stderr)
            speak("The alarm sound failed to play.")
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Alarm error: {error}", file=sys.stderr)
        speak("The alarm sound failed to play.")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def system_status() -> None:
    vision = run(["systemctl", "--user", "is-active", "jarvis-sam3.service"])
    vision_ok = vision.stdout.strip() == "active"

    bluetooth = run(["bluetoothctl", "devices", "Connected"])
    speaker_ok = "88:C6:26:66:52:1B" in bluetooth.stdout.upper()

    if vision_ok and speaker_ok:
        speak("All core systems are online. Vision monitoring is active, and the speaker is connected.")
    elif vision_ok:
        speak("Vision monitoring is active, but I cannot confirm the Bluetooth speaker connection.")
    elif speaker_ok:
        speak("The speaker is connected, but the vision watcher is not active.")
    else:
        speak("The vision watcher is offline, and I cannot confirm the Bluetooth speaker connection.")


def scene_summary() -> None:
    latest = MASKS / "latest"
    run_folder = latest.resolve() if latest.exists() else MASKS
    combined = run_folder / "combined_overlay.png"
    if not combined.exists():
        speak("I have not finished analyzing an image yet.")
        return

    counts: Counter[str] = Counter()
    manifest_path = run_folder / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            counts.update(
                detection["prompt"].replace("_", " ")
                for detection in manifest.get("detections", [])
                if detection.get("prompt")
            )
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f"Manifest error: {error}", file=sys.stderr)
    else:
        pattern = re.compile(r"^(.+)_([0-9]+)\.png$")
        raw_folder = run_folder / "raw_masks"
        search_folder = raw_folder if raw_folder.is_dir() else run_folder
        for path in search_folder.glob("*.png"):
            match = pattern.match(path.name)
            if match and not path.stem.endswith("_overlay"):
                counts[match.group(1).replace("_", " ")] += 1

    if not counts:
        speak("The latest image was analyzed, but none of the configured objects were detected.")
        return

    items: list[str] = []
    for label, count in sorted(counts.items()):
        name = label if count == 1 else f"{label}s"
        items.append(f"{count} {name}")

    if len(items) == 1:
        description = items[0]
    else:
        description = ", ".join(items[:-1]) + f", and {items[-1]}"

    analyzed_at = datetime.fromtimestamp(combined.stat().st_mtime).strftime("%I:%M %p").lstrip("0")
    speak(f"In the latest analyzed image, I found {description}. That result was completed at {analyzed_at}.")


def route(transcript: str) -> None:
    text = re.sub(r"[^a-z0-9' ]+", " ", transcript.lower())
    text = re.sub(r"\s+", " ", text).strip()
    print(f"Heard: {transcript.strip()}")

    if not text or text in {"blank audio", "silence"}:
        speak("I did not hear a command. Please try again.")
    elif CANCEL_PATTERN.search(text):
        print("Cancellation acknowledged.")
    elif re.search(r"\b(who am i|do you recognize me|who is speaking)\b", text):
        if SPEAKER == "Unknown":
            speak("I cannot confidently identify this speaker yet.")
        else:
            speak(f"You are {SPEAKER}.")
    elif re.search(r"\b(take|capture|snap)\b.*\b(picture|photo|image)\b", text):
        take_picture()
    elif re.search(r"\b(system status|status report|how are (?:the )?systems|systems? online)\b", text):
        system_status()
    elif re.search(r"\b(what do you see|what can you see|describe (?:the )?(?:scene|image)|scene summary)\b", text):
        scene_summary()
    elif re.search(r"\b(tell me a joke|make me laugh|joke)\b", text):
        speak(secrets.choice(JOKES))
    elif re.search(r"\b(flip (?:a |the )?coin|coin flip|heads or tails)\b", text):
        speak(f"The result is {secrets.choice(('heads', 'tails'))}.")
    elif re.search(r"\b(roll (?:a |the )?(?:die|dice)|dice roll)\b", text):
        speak(f"You rolled a {secrets.randbelow(6) + 1}.")
    elif re.search(r"\b(motivate me|inspire me|motivation)\b", text):
        speak(secrets.choice(MOTIVATION))
    elif re.search(r"\b(who are you|what are you)\b", text):
        speak("I am Jarvis, your locally operated voice and vision assistant. Still under construction, but already rather useful.")
    elif re.search(r"\b(how are you|how do you feel)\b", text):
        speak("All systems nominal. I am feeling exceptionally well compiled.")
    elif re.search(r"\b(open the pod bay doors|open pod bay doors)\b", text):
        speak("I'm sorry, but I cannot do that. Wrong assistant. I can take a picture, though.")
    elif re.search(r"\b(intruder alert|sound the alarm|red alert)\b", text):
        sound_alarm()
    elif re.search(r"\b(party mode|activate party mode)\b", text):
        speak("Party mode activated. Lighting and music modules remain suspiciously absent.")
    elif re.search(r"\b(good morning)\b", text):
        greeting = f"Good morning, {SPEAKER}." if SPEAKER != "Unknown" else "Good morning."
        speak(f"{greeting} Jarvis is online. Let us make today productive.")
    elif re.search(r"\b(good afternoon)\b", text):
        speak("Good afternoon. Jarvis is online and ready.")
    elif re.search(r"\b(good evening)\b", text):
        speak("Good evening. All systems are standing by.")
    elif re.search(r"\b(what can you do|help|commands)\b", text):
        speak("I can understand natural requests using my local AI, answer questions, use the camera, describe recent detections, report system status, remember short conversations, run my approved tools, and stop when you interrupt me.")
    elif re.search(r"\b(hello|hi|good morning|good afternoon|good evening)\b", text):
        greeting = f"Hello, {SPEAKER}." if SPEAKER != "Unknown" else "Hello."
        speak(f"{greeting} Jarvis is online and ready.")
    elif re.search(r"\b(thank you|thanks)\b", text):
        speak("You're welcome.")
    else:
        response = ask_ai(transcript)
        if response:
            speak(response)
        else:
            speak(f"I heard {transcript.strip()}, but my local intelligence is unavailable right now.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: jarvis_assistant.py <transcribed command>")
    route(" ".join(sys.argv[1:]))
