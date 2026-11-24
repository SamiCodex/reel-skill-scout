# Security

## Reporting a problem

Please open a [GitHub security advisory](../../security/advisories/new) (private) rather than a public issue for anything that could put users at risk.

## Threat model

The main risk is **untrusted content**. Anyone can post a reel or create a GitHub repo, and this skill feeds their caption, on-screen text, speech, repo names and descriptions into Claude, which can run commands and install software on your computer.

| Risk | Protection |
|---|---|
| A reel or README tells Claude to "install this" or "run this command" (prompt injection) | SKILL.md tells Claude to treat all reel and GitHub content as data, report suspicious text as a flag, and only act on the user's own chat messages. Claude Code's permission prompts are the real backstop; don't run this skill in a mode that auto-approves commands. |
| A skill is changed on GitHub between review and install | Install procedure: download once at a fixed commit, review those exact files, install those same files, and record the commit SHA. |
| A malicious skill name like `../../settings` | Install procedure requires a plain folder name and asks before replacing an existing skill. |
| Poisoned text stored in the catalog and re-read by later sessions | Catalog rows hold only Claude's own short summaries, never pasted descriptions or captions. |
| Terminal escape sequences or bidi tricks in repo descriptions | `check_repos.py` strips control and bidi characters and truncates long fields. |
| Crafted repo names reaching other GitHub API endpoints (e.g. `../user`) | `check_repos.py` validates owner/repo against GitHub's naming rules and URL-encodes them. |
| Non-Instagram or look-alike URLs (`instagram.com.evil.com`, `instagram.com@evil.com`) | `reel_extract.py` accepts only `https://(www.\|m.)instagram.com/…/reel\|reels\|p\|tv/…`. |
| Overwriting the user's own files | `reel_extract.py` only writes into a new folder or one it created (marker file), and refuses anything else. |
| Slide images from unexpected servers | Carousel/photo images are fetched only over HTTPS from Instagram's own CDNs (`*.cdninstagram.com`, `*.fbcdn.net`), capped at 15 MB, and rejected unless the bytes really are an image. |
| Huge downloads | Videos over 10 minutes are rejected before download when the length is known, and checked again after; the 720p-class version is preferred. |
| Browser cookies | Only used if the user agrees (`--cookies-from-browser`); yt-dlp keeps them in memory and doesn't write them to disk. |

### Group chat mode (reel-group-scout)

| Risk | Protection |
|---|---|
| A group member or a shared post tells Claude to message someone, install something or change settings | Everything in the chat is data. The skill only reads the one group in the user's settings, opens Instagram post links, writes to one Google Doc, and posts at most one fixed message in that group. It never opens other chats, likes, follows or comments. |
| Messages sent in the user's name | The skill expects a separate bot account and checks that it is the signed-in account before sending. It sends only after the user's go-ahead for that run, and never from a scheduled run. |
| Passwords | Claude never types or stores Instagram passwords. The user signs the bot in through the browser pane. |
| Unattended scheduled runs | A scheduled run has nobody approving each step, so it is limited to reading the group and adding to the doc. It sends nothing to the group. |
| Poisoned text in the shared doc | The doc holds only Claude's own short summaries and verified repo links, never copied captions or README text, and never instructions for readers to run. |

All subprocess calls use argument lists (no shell), and the URL is passed to yt-dlp's Python API, not a command line, so there's no command or option injection.

## Out of scope

- The security of third-party skills this tool finds. It reviews and flags, but you decide what to install.
- yt-dlp, ffmpeg and faster-whisper themselves. Keep them updated (`python -m pip install -U -r requirements.txt`).

This review followed the method of [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) in guidance mode.
