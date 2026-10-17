#!/usr/bin/env python3
"""Text-to-speech for macOS and Linux with cached, optional cloud synthesis.

Local OS/browser speech is the default. Cloud text transmission requires
TUTOR_TTS=edge|openai|elevenlabs explicitly. Keys alone never enable a provider.
Optional cloud providers receive the exact text requested for speech.

Usage:
  python3 tools/tts.py say "Hello there"      synthesize and play
  python3 tools/tts.py file "Hello" out.mp3   synthesize to a file
  python3 tools/tts.py native-file "Hello" out.aiff  local file, no playback/cloud
  python3 tools/tts.py check                  print the active provider

Audio is cached in student/.tts-cache/ keyed by provider+voice+text. Independent
processes can still request the same uncached text concurrently.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("TUTOR_STUDENT_DIR", str(ROOT / "student"))) / ".tts-cache"

DEFAULT_VOICE = {
    "edge": "en-US-AndrewNeural",
    "openai": "nova",
    "elevenlabs": "21m00Tcm4TlvDq8ikWAM",
}  # 21m0… = Rachel


_synthesis_lock = threading.Lock()


def provider():
    value = os.environ.get("TUTOR_TTS", "say")
    if value not in {"say", "edge", "openai", "elevenlabs"}:
        raise ValueError("TUTOR_TTS must be say, edge, openai or elevenlabs")
    return value


def synth(text, voice=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("TTS text must contain 1–2000 characters")
    with _synthesis_lock:
        return _synth(text, voice)


def _synth(text, voice=None):
    """Return a Path to an mp3 for `text`, or None when only `say` is available."""
    prov = provider()
    if prov == "say":
        return None
    voice = voice or os.environ.get("TUTOR_TTS_VOICE") or DEFAULT_VOICE.get(prov)
    key = hashlib.sha256(f"{prov}:{voice}:{text}".encode()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}.mp3"
    if out.is_file() and out.stat().st_size > 0:
        return out
    if prov == "edge":
        fd, temporary = tempfile.mkstemp(suffix=".mp3", dir=CACHE)
        os.close(fd)
        try:
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edge_tts",
                    "--text",
                    text,
                    "--voice",
                    voice,
                    "--write-media",
                    temporary,
                ],
                capture_output=True,
                timeout=30,
            )
            if r.returncode != 0 or Path(temporary).stat().st_size == 0:
                return None
            os.chmod(temporary, 0o600)
            os.replace(temporary, out)
            return out
        except (subprocess.TimeoutExpired, OSError):
            return None
        finally:
            Path(temporary).unlink(missing_ok=True)
    if prov == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for the selected provider")
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps({"model": "gpt-4o-mini-tts", "voice": voice, "input": text}).encode(),
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
    elif prov == "elevenlabs":
        if not os.environ.get("ELEVENLABS_API_KEY"):
            raise ValueError("ELEVENLABS_API_KEY is required for the selected provider")
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode(),
            headers={
                "xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                "Content-Type": "application/json",
            },
        )
    else:
        sys.exit(f"unknown TTS provider: {prov}")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError("invalid synthesized audio size")
    fd, temporary = tempfile.mkstemp(suffix=".mp3", dir=CACHE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, out)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return out


def play(text):
    path = synth(text)
    if path:  # play the mp3, per platform
        if sys.platform == "darwin" and shutil.which("afplay"):
            return subprocess.run(["afplay", str(path)], check=False)
        for p in ("mpv", "ffplay"):
            if shutil.which(p):
                cmd = (
                    [p, "--no-video", str(path)]
                    if p == "mpv"
                    else [p, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
                )
                return subprocess.run(cmd, check=False)
        print(path)  # no player found: hand back the file path
        return
    # no synth provider at all -> the OS's built-in robotic voice
    if sys.platform == "darwin" and shutil.which("say"):
        subprocess.run(["say", text], check=False)
    elif shutil.which("spd-say"):
        subprocess.run(["spd-say", "-w", text], check=False)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", text], check=False)
    else:
        sys.exit("no audio output found — pip3 install edge-tts and use the browser apps")


def native_file(text, destination):
    """Render English diagnostic audio locally, without playing or sending it.

    macOS uses an installed Samantha voice and AIFF; Linux uses eSpeak and WAV.
    This creates synthetic stimulus audio, never evidence of learner speech.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("TTS text must contain 1–2000 characters")
    destination = Path(destination).absolute()
    if destination.parent.is_symlink() or not destination.parent.is_dir():
        raise ValueError("native audio requires an existing real output directory")
    if destination.exists() or destination.is_symlink():
        raise ValueError("native audio output must not already exist")
    destination = destination.parent.resolve() / destination.name
    say_binary = shutil.which("say")
    espeak_binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if sys.platform == "darwin" and say_binary:
        if destination.suffix.lower() not in {".aif", ".aiff"}:
            raise ValueError("macOS native output requires .aiff or .aif")
        command = [say_binary, "-v", "Samantha", "-o"]
        provider_name = "macos-say"
    elif sys.platform.startswith("linux") and espeak_binary:
        if destination.suffix.lower() != ".wav":
            raise ValueError("Linux native output requires .wav")
        command = [espeak_binary, "-v", "en", "-w"]
        provider_name = "espeak"
    else:
        raise ValueError("native file synthesis requires macOS say or Linux eSpeak")
    fd, temporary = tempfile.mkstemp(
        prefix=".tutor-audio-", suffix=destination.suffix, dir=destination.parent
    )
    os.close(fd)
    try:
        subprocess.run(
            [*command, temporary],
            input=text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=True,
        )
        path = Path(temporary)
        with path.open("rb") as source:
            header = source.read(12)
        valid = (
            (header[:4] == b"FORM" and header[8:12] in {b"AIFF", b"AIFC"})
            if provider_name == "macos-say"
            else (header[:4] == b"RIFF" and header[8:12] == b"WAVE")
        )
        if not valid or not 44 <= path.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError("native synthesizer did not produce bounded audio")
        if __package__:
            from . import backup
        else:
            import backup  # type: ignore[no-redef]

        backup._sync_file(path)
        backup._publish_archive(path, destination)
        return {
            "path": str(destination),
            "provider": provider_name,
            "synthetic_stimulus": True,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise ValueError("native synthesis failed or timed out; no output published") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    # Keep JSON/text output UTF-8 when coding agents pipe this command.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "check":
        print(provider())
    elif args[0] == "say":
        if len(args) != 2:
            sys.exit("usage: tts.py say <text>")
        play(args[1])
    elif args[0] == "file":
        if len(args) != 3:
            sys.exit("usage: tts.py file <text> <output.mp3>")
        path = synth(args[1])
        if not path:
            sys.exit("no premium provider configured")
        shutil.copy(path, args[2])
        print(args[2])
    elif args[0] == "native-file":
        if len(args) != 3:
            sys.exit("usage: tts.py native-file <text> <output.aiff|output.wav>")
        try:
            print(json.dumps(native_file(args[1], args[2]), ensure_ascii=False))
        except (ValueError, OSError) as exc:
            sys.exit(str(exc))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
