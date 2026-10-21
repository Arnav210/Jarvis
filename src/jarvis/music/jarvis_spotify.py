#!/usr/bin/env python3
"""Spotify search and local playback controls for Jarvis.

The Spotify Web API uses Authorization Code with PKCE, so no client secret is
stored. Audio is played by the loopback-only go-librespot service API.
"""

from __future__ import annotations

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


CLIENT_ID = os.environ.get("JARVIS_SPOTIFY_CLIENT_ID", "e693dd7088cf467080dd8ced7d6aa48f")
REDIRECT_URI = os.environ.get("JARVIS_SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8765/callback")
PLAYER_API = os.environ.get("JARVIS_SPOTIFY_PLAYER_API", "http://127.0.0.1:3678")
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "jarvis"
TOKEN_FILE = STATE_DIR / "spotify-token.json"
SCOPES = (
    "user-read-private",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-modify-playback-state",
)


class SpotifyError(RuntimeError):
    pass


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 20,
) -> tuple[int, object | None]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(payload)
        except ValueError:
            details = payload
        raise SpotifyError(f"Request failed with HTTP {error.code}: {details}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise SpotifyError(f"Could not reach the Spotify service: {error}") from error


def load_token() -> dict[str, object]:
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SpotifyError("Spotify authorization is not complete yet.") from error
    except (OSError, ValueError, TypeError) as error:
        raise SpotifyError(f"Spotify authorization state is unreadable: {error}") from error
    if not isinstance(data, dict):
        raise SpotifyError("Spotify authorization state is invalid.")
    return data


def save_token(token: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = TOKEN_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(token, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(TOKEN_FILE)
    os.chmod(TOKEN_FILE, 0o600)


def token_request(fields: dict[str, str]) -> dict[str, object]:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    _, response = request_json(
        "https://accounts.spotify.com/api/token",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
    )
    if not isinstance(response, dict) or "access_token" not in response:
        raise SpotifyError("Spotify did not return an access token.")
    return response


def refresh_token(token: dict[str, object]) -> dict[str, object]:
    refresh = str(token.get("refresh_token", ""))
    if not refresh:
        raise SpotifyError("Spotify needs to be authorized again.")
    response = token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": CLIENT_ID,
        }
    )
    response.setdefault("refresh_token", refresh)
    response["expires_at"] = int(time.time()) + int(response.get("expires_in", 3600))
    save_token(response)
    return response


def access_token(*, force_refresh: bool = False) -> str:
    token = load_token()
    expires_at = int(token.get("expires_at", 0))
    if force_refresh or expires_at <= int(time.time()) + 60:
        token = refresh_token(token)
    value = str(token.get("access_token", ""))
    if not value:
        raise SpotifyError("Spotify needs to be authorized again.")
    return value


def spotify_api(path: str, *, query: dict[str, str] | None = None) -> object | None:
    url = "https://api.spotify.com/v1" + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Authorization": f"Bearer {access_token()}"}
    try:
        _, payload = request_json(url, headers=headers)
    except SpotifyError as error:
        if "HTTP 401" not in str(error):
            raise
        headers["Authorization"] = f"Bearer {access_token(force_refresh=True)}"
        _, payload = request_json(url, headers=headers)
    return payload


def local_player(path: str, *, method: str = "POST", payload: dict[str, object] | None = None) -> object | None:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        _, response = request_json(PLAYER_API + path, method=method, headers=headers, data=data, timeout=8)
        return response
    except SpotifyError as error:
        raise SpotifyError("The Jarvis Spotify player is not ready. Complete device pairing first.") from error


def authorize(*, manual: bool = False) -> None:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    expected_state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            parsed = urllib.parse.urlparse(self.path)
            values = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            result["state"] = values.get("state", [""])[0]
            result["code"] = values.get("code", [""])[0]
            result["error"] = values.get("error", [""])[0]
            ok = result["state"] == expected_state and bool(result["code"])
            body = (
                "Spotify authorization complete. You can close this tab."
                if ok
                else "Spotify authorization failed. Return to Codex for details."
            ).encode("utf-8")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    parameters = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": expected_state,
    }
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(parameters)
    print(f"AUTH_URL={url}", flush=True)

    if manual:
        print(
            "After approving access, copy the complete 127.0.0.1 callback URL "
            "from your browser and paste it below.",
            flush=True,
        )
        callback_url = input("CALLBACK_URL=").strip()
        parsed_callback = urllib.parse.urlparse(callback_url)
        if parsed_callback.hostname not in {"127.0.0.1", "::1"} or parsed_callback.path != "/callback":
            raise SpotifyError("That is not the expected Spotify callback URL.")
        values = urllib.parse.parse_qs(parsed_callback.query)
        result["state"] = values.get("state", [""])[0]
        result["code"] = values.get("code", [""])[0]
        result["error"] = values.get("error", [""])[0]
    else:
        parsed_redirect = urllib.parse.urlparse(REDIRECT_URI)
        server = HTTPServer(
            (parsed_redirect.hostname or "127.0.0.1", parsed_redirect.port or 8765),
            CallbackHandler,
        )
        server.timeout = 300
        server.handle_request()
        server.server_close()

    if result.get("error"):
        raise SpotifyError(f"Spotify authorization was declined: {result['error']}")
    if result.get("state") != expected_state:
        raise SpotifyError("Spotify authorization state did not match.")
    code = result.get("code", "")
    if not code:
        raise SpotifyError("Spotify authorization timed out.")

    token = token_request(
        {
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    )
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    save_token(token)
    print("Spotify Web API authorization saved securely.")


def search_track(query: str) -> tuple[str, str, str]:
    payload = spotify_api("/search", query={"q": query, "type": "track", "limit": "1"})
    if not isinstance(payload, dict):
        raise SpotifyError("Spotify returned an invalid search response.")
    tracks = payload.get("tracks", {})
    items = tracks.get("items", []) if isinstance(tracks, dict) else []
    if not items:
        raise SpotifyError(f"I could not find {query} on Spotify.")
    track = items[0]
    artists = ", ".join(artist.get("name", "") for artist in track.get("artists", []) if artist.get("name"))
    return str(track["uri"]), str(track.get("name", query)), artists


def play(query: str) -> str:
    uri, name, artists = search_track(query)
    local_player("/player/play", payload={"uri": uri})
    return f"Playing {name}" + (f" by {artists}." if artists else ".")


def now_playing() -> str:
    status = local_player("/status", method="GET")
    if not isinstance(status, dict) or status.get("stopped"):
        return "Spotify is not playing anything right now."
    track = status.get("track")
    if not isinstance(track, dict):
        return "Spotify is connected, but no track is loaded."
    name = str(track.get("name", "this track"))
    artists_value = track.get("artist_names", [])
    artists = ", ".join(str(value) for value in artists_value) if isinstance(artists_value, list) else str(artists_value)
    state = "paused on" if status.get("paused") else "playing"
    return f"Spotify is {state} {name}" + (f" by {artists}." if artists else ".")


def control(command: str) -> str:
    mapping = {
        "pause": ("/player/pause", "Music paused."),
        "resume": ("/player/resume", "Resuming music."),
        "next": ("/player/next", "Skipping to the next track."),
        "previous": ("/player/prev", "Going back to the previous track."),
    }
    path, message = mapping[command]
    local_player(path)
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    authorize_parser = subparsers.add_parser("authorize")
    authorize_parser.add_argument("--manual", action="store_true")
    subparsers.add_parser("status")
    play_parser = subparsers.add_parser("play")
    play_parser.add_argument("query", nargs="+")
    for name in ("pause", "resume", "next", "previous", "now-playing"):
        subparsers.add_parser(name)
    arguments = parser.parse_args()

    try:
        if arguments.command == "authorize":
            authorize(manual=arguments.manual)
        elif arguments.command == "status":
            token = load_token()
            print("Spotify Web API is authorized." if token.get("refresh_token") else "Spotify authorization is incomplete.")
        elif arguments.command == "play":
            print(play(" ".join(arguments.query)))
        elif arguments.command == "now-playing":
            print(now_playing())
        else:
            print(control(arguments.command))
    except SpotifyError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
