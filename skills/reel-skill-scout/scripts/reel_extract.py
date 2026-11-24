"""Download a public Instagram post - reel, video, photo or carousel - and turn it
into files Claude can read: the caption, slide images, video frames and a speech
transcript.

Usage:
    python reel_extract.py <instagram-url> <output-dir> [options]
    python reel_extract.py --check            # verify dependencies are installed

Options:
    --cookies-from-browser NAME   chrome / edge / firefox / safari - only if Instagram demands a login
    --whisper-model NAME          tiny / base / small (default) / medium / large-v3
    --max-frames N                cap on frames extracted per post (default 48)
    --no-transcript               skip speech-to-text
    --vocab TEXT                  terms that help Whisper spell names right ('' to disable)
    --allow-long                  allow videos longer than 10 minutes

Writes to <output-dir>:
    info.md              post type, account, date, stats and the full caption (always written first)
    slides/slide_NN.jpg  photo slides, full size (photo posts and carousels)
    transcript.md        timestamped speech transcript (local, faster-whisper)
    For a reel or single video post:
        reel.mp4, frames/fNNN.jpg, sheets/sheet_NN.jpg (4x4 contact sheets), frames.md
    For each video slide NN inside a carousel:
        video_slideNN.mp4, frames_slideNN/, sheets_slideNN/, frames_slideNN.md

Everything runs locally. Network use: the post download, and a one-time
download of the Whisper model (~500 MB for 'small') on first transcription.

Exit codes: 0 ok, 1 bad input, 2 download failed, 3 nothing to read in the post,
4 the (single) video is longer than 10 minutes.

Requires: pip install -r requirements.txt  (yt-dlp, imageio-ffmpeg, faster-whisper, numpy)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # noisy on Windows, harmless

MAX_SECONDS_DEFAULT = 600
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_SLIDES = 20  # Instagram's own carousel limit
MARKER = ".reel-extract"
INSTAGRAM_URL = re.compile(r"^https://(www\.|m\.)?instagram\.com/([\w.]+/)?(reels?|p|tv)/[\w-]+", re.I)
IMAGE_HOSTS = (".cdninstagram.com", ".fbcdn.net")
VIDEO_SUFFIXES = (".mp4", ".mkv", ".webm", ".mov")

DEFAULT_VOCAB = ("Claude, Claude Code, Anthropic, Opus, Sonnet, Haiku, skill, skills, SKILL.md, "
                 "MCP, MCP server, plugin, marketplace, slash command, CLAUDE.md, subagent, hooks, "
                 "GitHub, repo, npm, npx, Cursor, Codex, VS Code, Figma, Notion, Supabase, Playwright.")


def utf8_console():
    """Captions are full of emoji; don't crash on consoles with legacy code pages (cp874, cp1252...)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


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


# ---------------------------------------------------------------- download

def fetch(url, out, cookies_browser, max_seconds):
    """Download every video in the post; photo slides are recorded but not downloaded here."""
    import yt_dlp
    from yt_dlp.utils import match_filter_func

    opts = {
        "outtmpl": str(out / "media_%(playlist_index|0)s.%(ext)s"),
        # Frames are scaled to 720px wide anyway, so prefer the best version whose *smallest*
        # side is <= 720 ('res' in yt-dlp). Reels are vertical: a height filter would wrongly
        # pick a blurry 360x640 copy over the 720x1280 one and make small text unreadable.
        "format": "bv*+ba/b",
        "format_sort": ["res:720"],
        # refuse over-long videos *before* downloading (duration is often missing on
        # Instagram; '<?' lets those through and the post-download check catches them)
        "match_filter": match_filter_func(f"!is_live & duration <? {max_seconds}"),
        # photo slides have no video formats: read them instead of failing the whole post
        "ignore_no_formats_error": True,
        "playlist_items": f"1:{MAX_SLIDES}",
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg_exe(),
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "overwrites": True,
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    failed = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        # Read the whole post first, then download only the slides that are videos.
        # (Downloading the post in one go aborts as soon as it meets a photo slide.)
        info = ydl.extract_info(url, download=False)
        if not info:  # the only filter is the length limit, so a lone video was over it
            return None, []
        for n, entry in slides_of(info):
            if has_video_formats(entry):
                try:
                    ydl.process_info(dict(entry))
                except Exception as e:
                    failed.append(f"slide {n or 1} video download failed: {e}")
    return info, failed


def slides_of(info):
    """[(slide_number, entry)], slide_number 0 for a post that isn't a carousel."""
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        return [(int(e.get("playlist_index") or i), e) for i, e in enumerate(entries, 1)]
    return [(0, info)]


def downloaded_videos(out):
    vids = {}
    for p in out.glob("media_*"):
        m = re.fullmatch(r"media_(\d+)", p.stem)
        if m and p.suffix.lower() in VIDEO_SUFFIXES:
            vids[int(m[1])] = p
    return vids


def has_video_formats(entry):
    return any((f.get("vcodec") or "none") != "none" for f in (entry.get("formats") or []))


def image_url(entry):
    url = entry.get("thumbnail")
    if not url:
        thumbs = [t for t in (entry.get("thumbnails") or []) if t.get("url")]
        url = thumbs[-1]["url"] if thumbs else None  # yt-dlp sorts thumbnails best-last
    return url


def download_image(url, dest):
    """Fetch a slide image from Instagram's CDN only, size-capped, and check it really is an image."""
    parsed = urllib.parse.urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith(IMAGE_HOSTS):
        raise ValueError(f"refusing image from unexpected host {host!r}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image larger than 15 MB")
    if data[:3] == b"\xff\xd8\xff":
        dest.write_bytes(data)
        return
    if data[:4] == b"\x89PNG" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        tmp = dest.with_suffix(".src")  # convert to JPEG so any image reader can open it
        tmp.write_bytes(data)
        subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(tmp), str(dest)], check=True)
        tmp.unlink()
        return
    raise ValueError("downloaded file is not an image")


# ---------------------------------------------------------------- info.md

def fmt_date(d):
    d = str(d or "")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if re.fullmatch(r"\d{8}", d) else d


def merged_meta(info, slides):
    """Post-level fields, falling back to the first slide (carousels keep them there)."""
    first = slides[0][1] if slides else {}
    keys = ("id", "webpage_url", "original_url", "uploader", "uploader_id", "channel", "channel_id",
            "upload_date", "description", "title", "like_count", "comment_count", "view_count",
            "track", "artist")
    return {k: info.get(k) if info.get(k) is not None else first.get(k) for k in keys}


def post_type(slides):
    """Describe what the post *is* (not what happened to download)."""
    n_video = sum(1 for _, e in slides if has_video_formats(e))
    if slides and slides[0][0] == 0:
        return "reel / video" if n_video else "photo"
    return f"carousel ({len(slides)} slides: {len(slides) - n_video} photo, {n_video} video)"


def write_info(meta, kind, out, notes):
    def g(k):
        v = meta.get(k)
        return "" if v is None else str(v)

    handle = g("uploader_id") or g("channel_id") or g("channel")
    lines = ["# Post info", f"- URL: {g('webpage_url') or g('original_url')}", f"- Type: {kind}"]
    if g("uploader") or handle:
        lines.append(f"- Account: {g('uploader')}" + (f" (@{handle})" if handle else ""))
    if g("upload_date"):
        lines.append(f"- Posted: {fmt_date(g('upload_date'))}")
    stats = [f"{label}: {g(k)}" for label, k in (("Likes", "like_count"), ("Comments", "comment_count"),
                                                 ("Views", "view_count")) if g(k)]
    if stats:
        lines.append("- " + "  ".join(stats))
    if g("track") or g("artist"):
        lines.append(f"- Audio: {g('track')} - {g('artist')}".rstrip(" -"))
    lines += [f"- Note: {n}" for n in notes]
    caption = (g("description") or g("title")).strip() or "(none)"
    lines += ["", "## Caption", "", caption]
    (out / "info.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "info.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------- video

def probe_duration(video):
    """Read the real length from the file; Instagram often omits it from metadata."""
    r = subprocess.run([ffmpeg_exe(), "-i", str(video)], capture_output=True, text=True, errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def fresh_dir(path):
    """Empty a folder so files from an earlier run can't mix with this one."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def extract_frames(video, out, duration, max_frames, tag=""):
    ff = ffmpeg_exe()
    duration = duration or 60.0
    # aim for ~1 frame/sec, but cap the total so long videos stay cheap to read
    interval = max(1.0, duration / max(1, max_frames))
    fps = 1.0 / interval
    frames, sheets = out / f"frames{tag}", out / f"sheets{tag}"
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
            f"One frame every {interval:.1f}s. Sheets in {sheets.name}/ hold 16 frames each (4x4), "
            "left-to-right, top-to-bottom.", ""]
    for i, f in enumerate(files):
        t = i * interval + interval / 2
        rows.append(f"- {f.name}  ~{int(t // 60)}:{t % 60:04.1f}  (sheet_{i // 16 + 1:02d}, tile {i % 16 + 1})")
    (out / f"frames{tag}.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(files), len(list(sheets.glob("*.jpg")))


_MODEL = None


def transcribe(video, model_name, vocab=DEFAULT_VOCAB):
    """Return transcript lines for one video."""
    global _MODEL
    import numpy as np
    from faster_whisper import WhisperModel

    # Decode audio with ffmpeg ourselves (16 kHz mono float32) instead of letting
    # faster-whisper use PyAV, whose API changes between versions have broken it.
    pcm = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    if not pcm:
        return ["(video has no audio track)"]
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    if _MODEL is None:
        print(f"transcribing with whisper '{model_name}' (first run downloads the model)...", flush=True)
        _MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
    # initial_prompt biases Whisper toward spelling these terms correctly
    segments, info = _MODEL.transcribe(audio, vad_filter=True, initial_prompt=vocab or None)
    lines = [f"(detected language: {info.language}, p={info.language_probability:.2f})", ""]
    n = 0
    for s in segments:
        n += 1
        lines.append(f"[{int(s.start // 60)}:{s.start % 60:04.1f}] {s.text.strip()}")
    if n == 0:
        lines.append("(no speech detected - likely music only; rely on on-screen text and the caption)")
    return lines


# ---------------------------------------------------------------- main

def prepare_output(out):
    """Only ever write into a new folder or one this tool created; clear its previous results."""
    marker = out / MARKER
    if out.exists() and any(out.iterdir()) and not marker.exists():
        sys.exit(f"Output folder {out} already exists and wasn't created by this tool. "
                 "Pass a new, empty folder so nothing of yours gets overwritten.")
    out.mkdir(parents=True, exist_ok=True)
    marker.write_text("created by reel_extract.py - safe to delete this whole folder\n", encoding="utf-8")
    for p in out.iterdir():
        if p.name == MARKER:
            continue
        if p.is_dir() and not p.is_symlink() and re.fullmatch(r"(frames|sheets)(_slide\d+)?|slides", p.name):
            shutil.rmtree(p)
        # media_*/reel.*/video_slide* include yt-dlp leftovers like media_0.fdash-123v.mp4.part
        elif p.is_file() and (re.fullmatch(r"(media_\d+|reel|video_slide\d+)\..+", p.name)
                              or re.fullmatch(r"(info\.(md|json)|transcript\.md|frames(_slide\d+)?\.md)",
                                              p.name)):
            p.unlink()


def main():
    utf8_console()
    if "--check" in sys.argv[1:]:
        sys.exit(check_deps())

    ap = argparse.ArgumentParser(description="Turn an Instagram post into images, frames and a transcript.")
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
        sys.exit("Only Instagram is supported. Pass the full link, e.g. "
                 "https://www.instagram.com/reel/<code>/ or https://www.instagram.com/p/<code>/ "
                 "(also /reels/ and /tv/).")

    out = Path(a.outdir)
    prepare_output(out)
    max_seconds = float("inf") if a.allow_long else MAX_SECONDS_DEFAULT

    try:
        info, failed = fetch(a.url, out, a.cookies_from_browser, max_seconds)
    except Exception as e:
        msg = str(e)
        print(f"DOWNLOAD FAILED: {msg}", file=sys.stderr)
        if re.search(r"login|log in|rate.?limit|cookies|private|401|403", msg, re.I):
            print("Instagram wants a login. If the user agrees, retry with --cookies-from-browser chrome "
                  "(or edge/firefox/safari). Private accounts can't be downloaded at all.", file=sys.stderr)
        print("Instagram changes often - updating usually fixes other failures: "
              "python -m pip install -U yt-dlp", file=sys.stderr)
        sys.exit(2)

    if info is None:
        print(f"The video is longer than {MAX_SECONDS_DEFAULT // 60} minutes (skipped before downloading). "
              "Rerun with --allow-long if that's intended.", file=sys.stderr)
        sys.exit(4)
    slides = slides_of(info)
    videos = downloaded_videos(out)
    notes = list(failed)

    # photo slides (and photo posts): anything without a downloaded video and without video formats
    images = 0
    slide_dir = out / "slides"
    for n, entry in slides:
        if n in videos:
            continue
        if has_video_formats(entry):
            secs = entry.get("duration")
            if secs and float(secs) > max_seconds:
                notes.append(f"slide {n or 1} is a {float(secs) / 60:.0f} min video, skipped (over the limit)")
            continue  # download failures are already in notes
        url = image_url(entry)
        if not url:
            notes.append(f"slide {n or 1} has no image URL")
            continue
        slide_dir.mkdir(exist_ok=True)
        try:
            download_image(url, slide_dir / f"slide_{max(n, 1):02d}.jpg")
            images += 1
        except Exception as e:
            notes.append(f"slide {n or 1} image failed: {e}")

    meta = merged_meta(info, slides)
    kind = post_type(slides)
    write_info(meta, kind, out, notes)  # caption is saved even if everything below fails
    print(f"type: {kind}")
    if images:
        print(f"photo slides: {images} in {slide_dir}")

    for n in notes:
        print(f"note: {n}")
    if not videos and not images:
        single = slides[0][1] if slides else {}
        if single.get("duration") and float(single["duration"]) > max_seconds:
            print(f"Video is {float(single['duration']) / 60:.0f} minutes long (skipped before downloading). "
                  "Rerun with --allow-long if that's intended.", file=sys.stderr)
            sys.exit(4)
        if failed:
            print("DOWNLOAD FAILED: the video couldn't be downloaded (often a network hiccup - just retry). "
                  "info.md already has the caption.", file=sys.stderr)
            sys.exit(2)
        print("Nothing to read: no video or photos could be downloaded. info.md still has the caption; "
              "ask the user for screenshots if the caption isn't enough.", file=sys.stderr)
        sys.exit(3)

    single_video = len(slides) == 1 and slides[0][0] in videos
    per_video_frames = a.max_frames if single_video else max(16, a.max_frames // max(1, len(videos)))
    transcript = ["# Transcript", ""]
    for n in sorted(videos):
        src = videos[n]
        if single_video:
            tag, video = "", src.rename(out / f"reel{src.suffix}")
        else:
            tag, video = f"_slide{n:02d}", src.rename(out / f"video_slide{n:02d}{src.suffix}")
        duration = probe_duration(video)
        if duration > max_seconds:
            if single_video:
                print(f"Video is {duration / 60:.0f} minutes long. This tool is built for short videos; "
                      "rerun with --allow-long if that's intended.", file=sys.stderr)
                sys.exit(4)
            print(f"slide {n}: {duration / 60:.0f} min video skipped (over the limit)")
            continue
        n_frames, n_sheets = extract_frames(video, out, duration, per_video_frames, tag)
        print(f"video{tag or ''}: {duration:.0f}s, frames: {n_frames}, sheets: {n_sheets}")
        if not a.no_transcript:
            if not single_video:
                transcript += [f"## Slide {n}", ""]
            try:
                transcript += transcribe(video, a.whisper_model, a.vocab)
            except Exception as e:
                transcript.append(f"(transcription failed: {e})")
                print(f"TRANSCRIPT FAILED: {e}", file=sys.stderr)
            transcript.append("")
    if videos and not a.no_transcript:
        (out / "transcript.md").write_text("\n".join(transcript) + "\n", encoding="utf-8")
        print("transcript: done")
    print(f"output: {out}")


if __name__ == "__main__":
    main()
