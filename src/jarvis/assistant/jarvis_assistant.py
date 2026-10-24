#!/usr/bin/env python3
"""Small offline intent router for the Jarvis camera and voice system."""

from __future__ import annotations

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import json
import re
import secrets
import math
import os
import subprocess
import sys
import tempfile
import time
import wave
from collections import Counter
from datetime import datetime
from pathlib import Path
from jarvis.music.jarvis_music import MusicError, parse_voice as parse_local_music, perform as perform_local_music
from jarvis.ui.jarvis_status import emit as status_emit
from jarvis.ui.jarvis_status import attention as status_attention
from jarvis.assistant.room_info import intent as room_info_intent, answer as room_info_answer
from jarvis.assistant.mission_briefing import is_briefing_request, present as present_briefing
from jarvis.ui.jarvis_ironman import is_request as is_ironman_request, run_show as run_ironman_show
from jarvis.ui.jarvis_birthday import is_request as is_birthday_request, present as present_birthday, disable as disable_birthday


HOME = Path.home()
PROJECT = HOME / "Jarvis"
SPEAK = HOME / ".local" / "bin" / "jarvis-speak"
CAMERA = HOME / ".local" / "bin" / "jarvis-camera"
AI = PROJECT / "src/jarvis/assistant/jarvis_ai.py"
SPOTIFY = PROJECT / "src/jarvis/music/jarvis_spotify.py"
MASKS = PROJECT / "Masks"
SPEAKER = os.environ.get("JARVIS_SPEAKER", "Unknown")

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state")) / "jarvis"
STATE_FILE = STATE_DIR / "assistant.json"
DEFAULT_STATE = {"paused": False, "last_message": "", "audio_mode": "normal"}

CANCEL_PATTERN = re.compile(
    r"\b(?:jarvis\s+(?:please\s+)?(?:stop|cancel|be\s+quiet|quiet|shut\s+up)"
    r"|cancel\s+(?:that|it|this)|never\s+mind|be\s+quiet)\b"
)
END_SESSION_PATTERN = re.compile(
    r"\b(?:that's all|that is all|goodbye|bye jarvis|end (?:the )?conversation|"
    r"stop listening|no thanks|nothing else)\b"
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


def load_state() -> dict[str, object]:
    state = DEFAULT_STATE.copy()
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            state.update(saved)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass
    return state


def update_state(**updates: object) -> dict[str, object]:
    state = load_state()
    state.update(updates)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_FILE)
    return state


def remember_message(message: str) -> None:
    try:
        update_state(last_message=message)
    except OSError as error:
        print(f"State error: {error}", file=sys.stderr)


def speak(message: str, *, remember: bool = True) -> None:
    status_emit("speaking", "Playing the response through the room speaker.", reply=message)
    print(f"Jarvis: {message}", flush=True)
    if remember:
        remember_message(message)
    try:
        result = run([str(SPEAK), message], timeout=120)
        if result.returncode:
            status_attention("Speaker playback failed. Check the speaker connection.")
            print(result.stderr.strip(), file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        status_attention("Speaker playback failed or timed out.")
        print(f"Speech error: {error}", file=sys.stderr)


def set_paused(paused: bool) -> None:
    status_emit("action", 'Updating the pause state.')
    try:
        update_state(paused=paused)
    except OSError as error:
        print(f"State error: {error}", file=sys.stderr)
        speak("I could not change my listening state.", remember=False)
        return
    if paused:
        speak("Jarvis paused. Say Hey Jarvis, then resume Jarvis when you need me.", remember=False)
    else:
        speak("Jarvis resumed and ready.", remember=False)


def repeat_last_message() -> None:
    status_emit("action", 'Retrieving the previous response.')
    message = str(load_state().get("last_message", "")).strip()
    if message:
        speak(message, remember=False)
    else:
        speak("I do not have a previous message to repeat yet.", remember=False)


def set_audio_mode(mode: str) -> None:
    status_emit("action", 'Changing the audio mode.')
    if mode == "class":
        speak("Entering class mode. Muting the speakers now.", remember=False)
        result = run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"])
        if result.returncode:
            print(result.stderr.strip() or "Could not mute the default audio sink.", file=sys.stderr)
            speak("I could not mute the speakers.", remember=False)
            return
    elif mode == "normal":
        unmute = run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
        volume = run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "20%"])
        if unmute.returncode or volume.returncode:
            details = unmute.stderr.strip() or volume.stderr.strip()
            print(details or "Could not restore the default audio sink.", file=sys.stderr)
            speak("I could not fully restore normal audio.", remember=False)
            return
        speak("Normal mode restored. Speaker volume is twenty percent.", remember=False)
    else:
        raise ValueError(f"Unknown audio mode: {mode}")

    try:
        update_state(audio_mode=mode)
    except OSError as error:
        print(f"State error: {error}", file=sys.stderr)


def local_music_command(action: str, query: str = '') -> None:
    status_emit('action', 'Controlling the local music library.')
    try:
        message = perform_local_music(action, query)
    except MusicError as error:
        message = str(error)
        status_attention(message)
    speak(message)


def spotify_command(command: str, *arguments: str) -> None:
    status_emit("action", 'Sending the request to Spotify.')
    if not SPOTIFY.is_file():
        status_attention("Spotify controls are not installed.")
        speak("My Spotify controls are not installed yet.")
        return
    try:
        result = run([sys.executable, str(SPOTIFY), command, *arguments], timeout=40)
    except (OSError, subprocess.TimeoutExpired) as error:
        status_attention("Spotify did not respond. Check its service and network connection.")
        print(f"Spotify error: {error}", file=sys.stderr)
        speak("Spotify did not respond in time.")
        return
    output = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
    message = output.splitlines()[-1] if output else "Spotify could not complete that command."
    if result.returncode:
        status_attention("Spotify unavailable: " + message)
        print(message, file=sys.stderr)
    speak(message)


def ask_ai(transcript: str) -> str | None:
    """Ask the local allowlisted AI agent, returning None for safe fallback."""
    status_emit("processing", "Checking the request with local intelligence.")
    if os.environ.get("JARVIS_AI_ENABLED", "1") == "0" or not AI.is_file():
        status_attention("Local intelligence is disabled or not installed.")
        return None
    try:
        result = run([sys.executable, str(AI), transcript], timeout=170)
    except (OSError, subprocess.TimeoutExpired) as error:
        status_attention("Local intelligence failed or timed out. Say Hey Jarvis to try again.")
        print(f"AI error: {error}", file=sys.stderr)
        return None
    if result.returncode != 0:
        status_attention("Local intelligence is unavailable.")
        print(result.stderr.strip() or "Jarvis AI returned an error.", file=sys.stderr)
        return None
    response = result.stdout.strip()
    if not response:
        status_attention("Local intelligence returned no response.")
    elif response.endswith('?') and re.match(r"^(?:which\b|what (?:specific|would you like|is your (?:current goal|intended))|(?:could|can) you (?:clarify|specify|provide)|please (?:clarify|specify))", response, re.IGNORECASE):
        status_attention("Clarification requested. Say Hey Jarvis again to answer.")
    return response or None


def take_picture() -> None:
    status_emit("action", 'Requesting a camera capture.')
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
    status_emit("action", 'Playing the alarm.')
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
    status_emit("action", 'Checking system services.')
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
    status_emit("action", 'Reading the latest scene analysis.')
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


def captains_log_command(command: str) -> None:
    """Explicit log commands bypass AI and its generic music-play handler."""
    status_emit("action", 'Processing the captain log command.')
    if command == "start":
        # Speak first so the opening cue is not included in the recording.
        speak("Captain's log. Recording will begin after this message.")
    try:
        result = run([sys.executable, str(PROJECT / "src/jarvis/recording/jarvis_log.py"), command], timeout=1900 if command == "play" else 120 if command == "stop" else 30)
        message = (result.stdout if result.returncode == 0 else result.stderr).strip()
        if command == "start" and result.returncode == 0:
            print(message)
        else:
            speak(message or "Captain's log command complete.")
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Captain's log error: {error}", file=sys.stderr)
        speak("I could not complete that log command.")


def route(transcript: str) -> None:
    text = re.sub(r"[^a-z0-9' ]+", " ", transcript.lower())
    text = re.sub(r"\s+", " ", text).strip()
    status_emit("routing", "Matching the transcript to an available command.", transcript=transcript.strip())
    print(f"Heard: {transcript.strip()}", flush=True)

    state = load_state()
    resume_requested = bool(
        re.fullmatch(r"(?:hey )?(?:please )?(?:resume jarvis|jarvis resume|wake up jarvis|unpause jarvis)(?: please)?", text)
    )
    pause_requested = bool(
        re.fullmatch(r"(?:hey )?(?:please )?(?:pause jarvis|jarvis pause|go to sleep jarvis|stop responding)(?: please)?", text)
    )

    if not text or text in {"blank audio", "silence"}:
        status_attention("No clear command heard. Say Hey Jarvis and try again.")
        speak("I did not hear a command. Please try again.")
    elif resume_requested:
        set_paused(False)
    elif pause_requested:
        set_paused(True)
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?(?:end|stop|finish) (?:the )?(?:(?:captain'?s|captain s|personal) )?log", text):
        captains_log_command("stop")
    elif bool(state.get("paused", False)):
        print("Jarvis is paused; command ignored. Say 'resume Jarvis' after the wake word.")
    elif (room_request := room_info_intent(transcript)) is not None:
        status_emit("action", "Reading saved room observations from the dashboard.")
        speak(room_info_answer(room_request))
    elif is_briefing_request(text):
        present_briefing(speak, status_emit)
    elif re.fullmatch(r'(?:hey )?(?:jarvis )?(?:disable|deactivate) (?:the )?birthday protocol',text):
        disable_birthday()
        speak('Birthday protocol disabled.',remember=False)
    elif is_birthday_request(text):
        present_birthday(lambda message:speak(message,remember=False),status_emit)
    elif is_ironman_request(text):
        run_ironman_show()
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?daddy(?:'?s| s| is) home", text):
        status_emit(welcome_glow_started=str(time.time()))
        speak("Welcome home, sir. I see subtle entrances are still beneath you.")
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?(?:begin|start) (?:a |the )?(?:(?:captain'?s|captain s|personal) )?log", text):
        captains_log_command("start")
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?(?:captain'?s log status|log status)", text):
        captains_log_command("status")
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?play (?:the )?(?:latest|last) (?:(?:captain'?s|captain s|personal) )?log", text):
        captains_log_command("play")
    elif re.search(r"\b(?:repeat that|repeat your last (?:message|response)|say that again|what did you say)\b", text):
        repeat_last_message()
    elif re.search(r"\b(?:enter |activate |enable )?class mode\b", text):
        set_audio_mode("class")
    elif re.search(r"\b(?:enter |activate |enable )?normal mode\b|\b(?:exit|leave|disable) class mode\b", text):
        set_audio_mode("normal")
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?(?:(?:can|could|would) you )?(?:please )?(?:open|display|show(?: me)?) (?:the )?(?:latest|last|most recent) (?:masked|segmented|analyzed|annotated) (?:image|photo|picture)(?: for me)?(?: please)?", text):
        from jarvis.ui.jarvis_image_view import open_latest_image
        status_emit("action", "Opening the latest completed masked image.")
        speak(open_latest_image(masked=True))
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?(?:(?:can|could|would) you )?(?:please )?(?:open|display|show(?: me)?) (?:the )?(?:latest|last|most recent) (?:(?:saved|camera) )?(?:image|photo|picture)(?: for me)?(?: please)?", text):
        from jarvis.ui.jarvis_image_view import open_latest_image
        status_emit("action", "Opening the latest saved camera image.")
        speak(open_latest_image())
    elif re.fullmatch(r"(?:hey )?(?:jarvis )?(?:(?:can|could|would) you )?(?:please )?(?:play|start|run|activate|show(?: me)?) (?:(?:a|the) )?(?:halloween|spooky)(?: (?:show|animation|mode))?(?: please)?", text):
        from jarvis.ui.jarvis_halloween import run_show
        if run_show():
            speak("Happy Halloween, sir.")
    elif (music_request := parse_local_music(text)) is not None:
        local_music_command(*music_request)
    elif re.search(r"\b(?:what(?:'s| is) playing|what song is (?:this|playing)|now playing)\b", text):
        spotify_command("now-playing")
    elif re.search(r"\b(?:pause|stop) (?:the )?(?:music|song|spotify)\b", text):
        spotify_command("pause")
    elif re.search(r"\b(?:resume|continue|play) (?:the )?(?:music|spotify)\b", text):
        spotify_command("resume")
    elif re.search(r"\b(?:next|skip)(?: song| track)?\b", text):
        spotify_command("next")
    elif re.search(r"\b(?:previous|last|go back)(?: song| track)?\b", text):
        spotify_command("previous")
    elif match := re.search(r"\bplay (?:the song |song |track )?(.+?)(?: on spotify)?$", text):
        query = match.group(1).strip()
        if query:
            spotify_command("play", query)
        else:
            speak("Tell me which song or artist to play.")
    elif CANCEL_PATTERN.search(text):
        print("Cancellation acknowledged.")
    elif END_SESSION_PATTERN.search(text):
        speak("Understood. I'll wait for you to call me again.")
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
        speak("I can report the latest recorded people count, today's peak occupancy and busiest observation, the last capture time, and how many captures were analyzed today. I can also give the daily mission briefing, answer questions, inspect folder sizes and free disk space, find files, check memory and CPU load, report service status, use the camera, open the latest saved or masked image, play a Halloween ASCII show, control local music, repeat my last message, and switch audio modes.")
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
