"""Download a public Instagram reel and turn it into files Claude can read:
frames as images, a speech transcript, and the caption.

Usage:
    python reel_extract.py <instagram-reel-url> <output-dir> [options]
    python reel_extract.py --check            # verify dependencies are installed

Options:
    --cookies-from-browser NAME   chrome / edge / firefox / safari - only if the site demands a login
    --whisper-model NAME          tiny / base / small (default) / medium / large-v3
    --max-frames N                cap on frames extracted (default 48)
    --no-transcript               skip speech-to-text
    --vocab TEXT                  terms that help Whisper spell names right ('' to disable)
    --allow-long                  allow videos longer than 10 minutes

Writes to <output-dir>:
    info.md              account, date, duration, stats and the full caption
    transcript.md        timestamped speech transcript (local, faster-whisper)
    sheets/sheet_NN.jpg  4x4 contact sheets for a fast pass
    frames/fNNN.jpg      full-size frames for reading small text
    frames.md            timestamp of every frame and where it sits on a sheet

Everything runs locally. Network use: the video download, and a one-time
download of the Whisper model (~500 MB for 'small') on first transcription.

Requires: pip install -r requirements.txt  (yt-dlp, imageio-ffmpeg, faster-whisper, numpy)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # noisy on Windows, harmless

MAX_SECONDS_DEFAULT = 600
MARKER = ".reel-extract"
INSTAGRAM_URL = re.compile(r"^https://(www\.|m\.)?instagram\.com/([\w.]+/)?(reels?|p|tv)/[\w-]+", re.I)
VIDEO_SUFFIXES = (".mp4", ".mkv", ".webm", ".mov")

DEFAULT_VOCAB = ("Claude, Claude Code, Anthropic, Opus, Sonnet, Haiku, skill, skills, SKILL.md, "
                 "MCP, MCP server, plugin, marketplace, slash command, CLAUDE.md, subagent, hooks, "
                 "GitHub, repo, npm, npx, Cursor, Codex, VS Code, Figma, Notion, Supabase, Playwright.")


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if found:
            return found
        sys.exit("ffmpeg not found. Run: pip install imageio-ffmpeg")


def check_deps():
    ok = True
    for mod, pip_name in (("yt_dlp", "yt-dlp"), ("imageio_ffmpeg", "imageio-ffmpeg"),
                          ("faster_whisper", "faster-whisper"), ("numpy", "numpy")):
        try:
            __import__(mod)
            print(f"ok       {pip_name}")
        except Exception as e:
            ok = False
            print(f"MISSING  {pip_name}  ({e.__class__.__name__}: {e})")
    try:
        print(f"ok       ffmpeg at {ffmpeg_exe()}")
    except SystemExit as e:
        ok = False
        print(f"MISSING  ffmpeg  ({e})")
    print("all good" if ok else "install missing packages with: python -m pip install -r requirements.txt")
    return 0 if ok else 1


def download(url, out, cookies_browser, max_seconds):
    import yt_dlp
    from yt_dlp.utils import match_filter_func

    opts = {
        "outtmpl": str(out / "reel.%(ext)s"),
        # Frames are scaled to 720px wide anyway, so prefer the best version whose *smallest*
        # side is <= 720 ('res' in yt-dlp). Reels are vertical: a height filter would wrongly
        # pick a blurry 360x640 copy over the 720x1280 one and make small text unreadable.
        "format": "bv*+ba/b",
        "format_sort": ["res:720"],
        # refuse over-long videos *before* downloading (duration is often missing on
        # Instagram; '<?' lets those through and the post-download check catches them)
        "match_filter": match_filter_func(f"!is_live & duration <? {max_seconds}"),
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg_exe(),
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "overwrites": True,
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            return info, None
        info = entries[0]
    video = next((p for p in sorted(out.glob("reel.*")) if p.suffix.lower() in VIDEO_SUFFIXES), None)
    return info, video


def fmt_date(d):
    d = str(d or "")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if re.fullmatch(r"\d{8}", d) else d


def write_info(info, out, duration):
    def g(k):
        v = info.get(k)
        return "" if v is None else str(v)

    handle = g("uploader_id") or g("channel_id") or g("channel")
    lines = ["# Video info", f"- URL: {g('webpage_url') or g('original_url')}"]
    if g("uploader") or handle:
        lines.append(f"- Account: {g('uploader')}" + (f" (@{handle})" if handle else ""))
    if g("upload_date"):
        lines.append(f"- Posted: {fmt_date(g('upload_date'))}")
    if duration:
        lines.append(f"- Duration: {duration:.0f} s")
    stats = [f"{label}: {g(k)}" for label, k in (("Likes", "like_count"), ("Comments", "comment_count"),
                                                 ("Views", "view_count")) if g(k)]
    if stats:
        lines.append("- " + "  ".join(stats))
    if g("track") or g("artist"):
        lines.append(f"- Audio: {g('track')} - {g('artist')}".rstrip(" -"))
    caption = (g("description") or g("title")).strip() or "(none)"
    lines += ["", "## Caption", "", caption]
    (out / "info.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def probe_duration(video):
    """Read the real length from the file; Instagram often omits it from metadata."""
    r = subprocess.run([ffmpeg_exe(), "-i", str(video)], capture_output=True, text=True, errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def fresh_dir(path):
    """Empty a folder so frames from an earlier run can't mix with this one."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def extract_frames(video, out, duration, max_frames):
    ff = ffmpeg_exe()
    duration = duration or 60.0
    # aim for ~1 frame/sec, but cap the total so long videos stay cheap to read
    interval = max(1.0, duration / max(1, max_frames))
    fps = 1.0 / interval
    frames, sheets = out / "frames", out / "sheets"
    fresh_dir(frames)
    fresh_dir(sheets)
    subprocess.run([ff, "-loglevel", "error", "-y", "-i", str(video),
                    "-vf", f"fps={fps},scale=720:-2", "-q:v", "3",
                    str(frames / "f%03d.jpg")], check=True)
    subprocess.run([ff, "-loglevel", "error", "-y", "-i", str(video),
                    # 4x4 tiles at 300px: headline text stays legible at ~half the images of 3x3
                    "-vf", f"fps={fps},scale=300:-2,tile=4x4:padding=6:color=white",
                    "-q:v", "3", str(sheets / "sheet_%02d.jpg")], check=True)
    files = sorted(frames.glob("f*.jpg"))
    rows = ["# Frame timestamps", "",
            f"One frame every {interval:.1f}s. Sheets hold 16 frames each (4x4), "
            "left-to-right, top-to-bottom.", ""]
    for i, f in enumerate(files):
        t = i * interval + interval / 2
        rows.append(f"- {f.name}  ~{int(t // 60)}:{t % 60:04.1f}  (sheet_{i // 16 + 1:02d}, tile {i % 16 + 1})")
    (out / "frames.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(files), len(list(sheets.glob("*.jpg")))


def transcribe(video, out, model_name, vocab=DEFAULT_VOCAB):
    import numpy as np
    from faster_whisper import WhisperModel

    # Decode audio with ffmpeg ourselves (16 kHz mono float32) instead of letting
    # faster-whisper use PyAV, whose API changes between versions have broken it.
    pcm = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    if not pcm:
        (out / "transcript.md").write_text("# Transcript\n\n(video has no audio track)\n", encoding="utf-8")
        return
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    print(f"transcribing with whisper '{model_name}' (first run downloads the model)...", flush=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    # initial_prompt biases Whisper toward spelling these terms correctly
    segments, info = model.transcribe(audio, vad_filter=True, initial_prompt=vocab or None)
    lines = [f"# Transcript (detected language: {info.language}, p={info.language_probability:.2f})", ""]
    n = 0
    for s in segments:
        n += 1
        lines.append(f"[{int(s.start // 60)}:{s.start % 60:04.1f}] {s.text.strip()}")
    if n == 0:
        lines.append("(no speech detected - likely music only; rely on on-screen text and the caption)")
    (out / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if "--check" in sys.argv[1:]:
        sys.exit(check_deps())

    ap = argparse.ArgumentParser(description="Turn a short video into frames + transcript for Claude.")
    ap.add_argument("url")
    ap.add_argument("outdir")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="chrome / edge / firefox / safari - use only if Instagram demands a login")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--max-frames", type=int, default=48)
    ap.add_argument("--no-transcript", action="store_true")
    ap.add_argument("--vocab", default=DEFAULT_VOCAB,
                    help="comma-separated terms to help Whisper spell names right ('' to disable)")
    ap.add_argument("--allow-long", action="store_true",
                    help=f"allow videos longer than {MAX_SECONDS_DEFAULT // 60} minutes")
    a = ap.parse_args()

    if not INSTAGRAM_URL.match(a.url):
        sys.exit("Only Instagram reels are supported. Pass the full link, e.g. "
                 "https://www.instagram.com/reel/<code>/ (also /reels/, /p/ and /tv/ links).")

    out = Path(a.outdir)
    # This tool deletes and recreates files in its output folder (frames/, sheets/, reel.*).
    # Only ever do that in a new folder or one this tool created, never a user's existing folder.
    marker = out / MARKER
    if out.exists() and any(out.iterdir()) and not marker.exists():
        sys.exit(f"Output folder {out} already exists and wasn't created by this tool. "
                 "Pass a new, empty folder so nothing of yours gets overwritten.")
    out.mkdir(parents=True, exist_ok=True)
    marker.write_text("created by reel_extract.py - safe to delete this whole folder\n", encoding="utf-8")
    # clear a previous run's results so nothing stale (video, transcript, caption) gets mixed in
    for old in out.glob("reel.*"):
        if old.suffix.lower() in VIDEO_SUFFIXES + (".part", ".ytdl"):
            old.unlink()
    for name in ("info.md", "info.json", "transcript.md", "frames.md"):
        (out / name).unlink(missing_ok=True)

    max_seconds = float("inf") if a.allow_long else MAX_SECONDS_DEFAULT
    try:
        info, video = download(a.url, out, a.cookies_from_browser, max_seconds)
    except Exception as e:
        msg = str(e)
        print(f"DOWNLOAD FAILED: {msg}", file=sys.stderr)
        if re.search(r"login|log in|rate.?limit|cookies|private|401|403", msg, re.I):
            print("Instagram wants a login. If the user agrees, retry with --cookies-from-browser chrome "
                  "(or edge/firefox/safari). Private accounts can't be downloaded at all.", file=sys.stderr)
        print("Instagram changes often - updating usually fixes other failures: "
              "python -m pip install -U yt-dlp", file=sys.stderr)
        sys.exit(2)
    if not video:
        if info and info.get("duration") and float(info["duration"]) > max_seconds:
            print(f"Video is {float(info['duration']) / 60:.0f} minutes long (skipped before downloading). "
                  "Rerun with --allow-long if that's intended.", file=sys.stderr)
            sys.exit(4)
        print("DOWNLOAD FAILED: no video file. It may be a photo/carousel post - ask for screenshots.",
              file=sys.stderr)
        sys.exit(3)

    duration = float(info.get("duration") or 0) or probe_duration(video)
    if duration > MAX_SECONDS_DEFAULT and not a.allow_long:
        print(f"Video is {duration / 60:.0f} minutes long. This tool is built for short videos; "
              "rerun with --allow-long if that's intended (transcription will be slow).", file=sys.stderr)
        sys.exit(4)

    (out / "info.json").write_text(json.dumps({k: info.get(k) for k in (
        "id", "webpage_url", "uploader", "uploader_id", "channel", "upload_date", "duration", "description",
        "title", "like_count", "comment_count", "view_count", "track", "artist")}, indent=2, default=str),
        encoding="utf-8")
    write_info(info, out, duration)
    n_frames, n_sheets = extract_frames(video, out, duration, a.max_frames)
    print(f"video: {video}\nduration: {duration:.0f}s\nframes: {n_frames}  sheets: {n_sheets}")

    if not a.no_transcript:
        try:
            transcribe(video, out, a.whisper_model, a.vocab)
            print("transcript: done")
        except Exception as e:
            (out / "transcript.md").write_text(f"# Transcript\n\n(transcription failed: {e})\n", encoding="utf-8")
            print(f"TRANSCRIPT FAILED: {e}", file=sys.stderr)
    print(f"output: {out}")


if __name__ == "__main__":
    main()
