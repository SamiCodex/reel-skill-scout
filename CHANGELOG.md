# Changelog

## 1.3.0 (2026-11-25)

- **reel-group-scout moved to its own repo:** [SamiCodex/reel-group-scout](https://github.com/SamiCodex/reel-group-scout). This plugin now contains only reel-skill-scout, with no bot account or group chat parts. If you used group chat mode, install reel-group-scout from its new repo.

## 1.2.0 (2026-11-24)

- **New skill: reel-group-scout.** Reads an Instagram group chat (through the Claude desktop app's built-in browser, signed in to a separate bot account), finds every reel and post shared since the last check, runs reel-skill-scout on each, and adds a section per post to a shared Google Doc. It posts in the group only on the user's go-ahead, never from a scheduled run, and treats everything in the chat as data.
- Carousels with video slides are now tested on a real post.

## 1.1.0 (2026-11-24)

- **Photo posts and carousels.** Every slide is read: photo slides are saved at full size (`slides/`), and each video slide gets its own frames, contact sheets and transcript section. Previously only the first video was used and photo posts failed.
- **The caption is always saved**, written before anything else, so it survives a failed download.
- **No more crashes on emoji** in captions or repo descriptions on Windows consoles with legacy code pages (e.g. cp874, cp1252).
- More reliable downloads: automatic retries and timeouts; a failed download now reports "download failed" (exit 2) instead of "nothing to read".
- Reruns into the same folder also clear partial `.part` downloads and old slide folders.

## 1.0.0 (2026-11-24)

First release.

- Watches public Instagram reels (`/reel/`, `/reels/`, `/p/`, `/tv/`): yt-dlp download, ffmpeg frames and 4x4 contact sheets, local faster-whisper transcript primed with Claude vocabulary.
- Extracts recommended skills, plugins, MCP servers, connectors, commands and tips; verifies GitHub repos with live stats (`check_repos.py`).
- Rates each item for the user's own workflow and keeps a catalog at `~/.claude/skill-scout/catalog.md`.
- Installs nothing without the user's yes, and reviews third-party code before recommending it.
- Instagram only: other sites are rejected.
