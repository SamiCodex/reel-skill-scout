# Reel Skill Scout

**Stop searching for Claude skills one by one.** Paste a link to an Instagram reel or post about Claude, and Claude watches or reads it, finds every skill, plugin and MCP server it recommends, verifies the GitHub repos, and tells you which ones are actually worth installing for *your* workflow.

A [Claude Code](https://claude.com/claude-code) skill for **Instagram**: reels, photo posts and carousels. Everything runs on your own computer.

```
you:    https://www.instagram.com/reel/DgBVPFEOaA3/
claude: This reel counts down the 10 fastest-growing Claude repos on GitHub this month...
```

| # | Name | What it does | GitHub | Stars | Useful for you? |
|---|---|---|---|---|---|
| 3 | HyperFrames | Describe a video; Claude builds it as code and renders an MP4 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | 89.0k (Vendor) | **High**: polished reels without editing software |
| 7 | FFmpeg Skill | Fixes raw clips locally: stabilise, brighten, cut silences, captions | [kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) | 10.3k | **High**: clean up footage before posting |
| 6 | Claude BugHunter | 84 skills for bug bounties and red-team work | [elementalsouls/Claude-BugHunter](https://github.com/elementalsouls/Claude-BugHunter) | 20.0k | **Low**: built for security professionals |
| … | | | | | |

*(Excerpt from a real run; ratings were for a content creator. The full example is in [examples/example-report.md](examples/example-report.md).)*

## What it does

1. **Watches the reel or reads the post.** Downloads it, pulls video frames (read as images), every carousel/photo slide at full size, a local speech transcript, and the caption.
2. **Extracts every recommendation:** skills, plugins, MCP servers, connectors, slash commands, CLAUDE.md tips, prompts.
3. **Tracks each one down:** finds the real GitHub repo (often shown on screen even when the creator says "comment for the link"), checks it exists, and pulls live stars, last update and license.
4. **Rates it for you:** High / Medium / Low / Already covered, based on what you use Claude for (asked once, then remembered).
5. **Keeps a catalog** at `~/.claude/skill-scout/catalog.md`, so a tool mentioned in five reels is looked up once.
6. **Installs your picks, only when you say yes**, after reading the code for anything risky.

Paste several reels at once and you get one merged list. Tools that several creators recommend independently get flagged.

## Requirements

- Claude Code (CLI, desktop app or IDE extension)
- Python 3.9+
- ~600 MB of disk for the speech model (downloaded on first use)

## Install

**As a plugin** (in Claude Code):

```
/plugin marketplace add SamiCodex/reel-skill-scout
/plugin install reel-skill-scout@reel-skill-scout
```

**Or manually**: copy `skills/reel-skill-scout/` into `~/.claude/skills/`.

Then install the Python packages:

```
python -m pip install -r requirements.txt
```

(macOS/Linux: use `python3`. Windows: if `python` says "not found", install Python from python.org or with `winget install Python.Python.3.12`, then open a new terminal.)

Check everything is ready:

```
python ~/.claude/skills/reel-skill-scout/scripts/reel_extract.py --check
```

Claude also runs this check itself and will offer to install anything missing.

## Use

Just paste a reel or post link. No special command needed:

> https://www.instagram.com/reel/…

> https://www.instagram.com/p/… (a carousel of skill screenshots)

> what skills is this guy recommending? https://www.instagram.com/reel/…

> here are 3 reels, which of these tools should I actually install? …

| Post type | Supported |
|---|---|
| Reels (`/reel/`, `/reels/`) | ✅ Tested |
| Carousels (`/p/`): photo slides | ✅ Tested |
| Carousels with video slides | Supported, not yet tested on a real post (each video slide gets its own frames and transcript) |
| Single photo or video posts (`/p/`, `/tv/`) | Supported, not yet tested on a real post |

Only **public** posts work without logging in. The caption is always saved first, even if the rest of a post can't be downloaded. **Instagram only:** links from other sites are rejected.

## Token cost

Roughly **15–20k tokens per reel** (2–3 minutes long): ~3 contact-sheet images, a few full-size frames where text is small, the transcript, and the GitHub lookups. Most of the cost is images; the script packs 16 frames per sheet to keep it low. A carousel costs about **1.5–2k tokens per slide** (a 5-slide post is ~10k).

## Privacy and responsible use

- **Runs locally.** The video, frames and transcript stay on your computer. Network calls: the reel download, a one-time Whisper model download, and the public GitHub API for repo stats.
- **Personal use.** Downloading from Instagram is against Instagram's terms of use, even for public reels. This tool is for privately analysing public reels you're already watching. Don't use it to re-upload or redistribute anyone's content, and delete the downloaded files when you're done (they go to a temporary folder).
- **Logging in is opt-in.** If Instagram blocks anonymous downloads, Claude will ask before using `--cookies-from-browser`, which reads your browser's logged-in session. Use it sparingly: heavy automated downloading can get an account rate-limited or flagged.
- **Third-party skills are code.** Before installing anything it finds, Claude reads it and flags anything that runs downloaded code, asks for API keys, or sends data elsewhere. You decide what gets installed.

## Troubleshooting

| Problem | Fix |
|---|---|
| `DOWNLOAD FAILED` | `python -m pip install -U yt-dlp`. Instagram changes constantly, and a newer yt-dlp usually fixes it |
| "login required" / rate limited | Wait a while, or let Claude retry with `--cookies-from-browser chrome` |
| "Only Instagram is supported" | Use the full `instagram.com/reel/…` or `instagram.com/p/…` link (Share → Copy link) |
| `note: slide N …` | Part of a carousel was skipped; the report mentions it |
| `Python was not found` (Windows) | That's the Microsoft Store placeholder; install real Python (see Install) |
| Transcript has wrong names | Normal for Whisper. Claude cross-checks names against on-screen text. For accents/noise, ask for `--whisper-model medium` |
| First run is slow | One-time ~500 MB Whisper model download |
| `RATE LIMITED` on repo checks | GitHub allows 60 lookups/hour without a token; set `GITHUB_TOKEN` for more |

## How it works

```
skills/reel-skill-scout/
├── SKILL.md              instructions Claude follows
└── scripts/
    ├── reel_extract.py   yt-dlp download → photo slides + ffmpeg frames/4x4 contact sheets → faster-whisper transcript
    └── check_repos.py    verifies owner/repo via the GitHub API (stars, last push, license, archived)
```

You can also run the scripts yourself:

```
python scripts/reel_extract.py "https://www.instagram.com/reel/<code>/" ./out
python scripts/check_repos.py vercel-labs/agent-browser heygen-com/hyperframes
```

## License

MIT. See [LICENSE](LICENSE). Not affiliated with Anthropic or Instagram/Meta.
