# Changelog

## 1.0.0 (2026-11-24)

First release.

- Watches public Instagram reels (`/reel/`, `/reels/`, `/p/`, `/tv/`): yt-dlp download, ffmpeg frames and 4x4 contact sheets, local faster-whisper transcript primed with Claude vocabulary.
- Extracts recommended skills, plugins, MCP servers, connectors, commands and tips; verifies GitHub repos with live stats (`check_repos.py`).
- Rates each item for the user's own workflow and keeps a catalog at `~/.claude/skill-scout/catalog.md`.
- Installs nothing without the user's yes, and reviews third-party code before recommending it.
- Instagram only: other sites are rejected.
