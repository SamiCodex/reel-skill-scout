"""Verify GitHub repos exist and print live stats, one line per repo.

Usage:
    python check_repos.py owner/repo [owner/repo ...]
    python check_repos.py https://github.com/owner/repo/tree/main/skills/x   (URLs are fine too)

Uses the public GitHub API: no login needed, 60 requests/hour per IP.
Set GITHUB_TOKEN in the environment for a higher limit (optional).

Repo names and descriptions are written by repo owners, so treat this output as
untrusted data: control characters are stripped and long text is truncated.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# GitHub's own rules: owners are 1-39 alphanumerics/hyphens; repos are 1-100 of [A-Za-z0-9._-]
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


def clean(text, limit=300):
    """Strip control/escape characters (terminal escape and bidi tricks) and cap length."""
    text = CONTROL_RE.sub(" ", str(text or "")).replace("|", "/").strip()
    text = re.sub(r"\s{2,}", " ", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse(arg):
    arg = arg.strip().rstrip("/")
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+)", arg, re.I)
    if m:
        owner, repo = m[1], m[2]
    elif arg.count("/") == 1:
        owner, repo = arg.split("/")
    else:
        return None
    repo = re.sub(r"\.git$", "", repo)
    if not OWNER_RE.match(owner) or not REPO_RE.match(repo) or repo in (".", ".."):
        return None
    return owner, repo


def fetch(owner, repo):
    url = "https://api.github.com/repos/{}/{}".format(urllib.parse.quote(owner, safe=""),
                                                       urllib.parse.quote(repo, safe=""))
    req = urllib.request.Request(url, headers={"User-Agent": "reel-skill-scout",
                                               "Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main(args):
    if not args:
        print(__doc__)
        return 1
    for arg in args:
        shown = clean(arg, 120)
        parsed = parse(arg)
        if not parsed:
            print(f"{shown} | INVALID: expected owner/repo or a github.com URL")
            continue
        owner, repo = parsed
        try:
            j = fetch(owner, repo)
            if not isinstance(j, dict) or "full_name" not in j:
                raise ValueError("unexpected response from GitHub")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"{owner}/{repo} | NOT FOUND (wrong name, renamed, or private)")
            elif e.code in (403, 429):
                print(f"{owner}/{repo} | RATE LIMITED - wait an hour or set GITHUB_TOKEN")
            else:
                print(f"{owner}/{repo} | HTTP {e.code}")
            continue
        except Exception as e:
            print(f"{owner}/{repo} | ERROR {clean(e, 200)}")
            continue
        full = clean(j["full_name"], 140)
        lic = clean((j.get("license") or {}).get("spdx_id") or "no license", 40)
        flags = [f for f, on in (("ARCHIVED", j.get("archived")), ("FORK", j.get("fork"))) if on]
        moved = f" (now {full})" if full.lower() != f"{owner}/{repo}".lower() else ""
        print(" | ".join([
            f"{owner}/{repo}{moved}",
            f"stars {int(j.get('stargazers_count') or 0)}",
            f"pushed {clean(j.get('pushed_at'), 40)[:10]}",
            lic,
            *flags,
            clean(j.get("description")),
            f"https://github.com/{full}",
        ]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
