#!/usr/bin/env python3
"""Prepare and validate bot update announcements (bot/announcements/NNNN.md).

  python scripts/check_update_announcement.py prepare
      Show the next announcement id, its base commit, and the NET diff of
      deployed code since the previous announcement — the only material an
      announcement may describe.

  python scripts/check_update_announcement.py check [--require-current]
      Validate the template and the base/head chain against git history.
      --require-current also fails when deployed code changed after the
      latest announcement's head (run it right before every deploy).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.bot_update_announcement_service import (  # noqa: E402
    ANNOUNCEMENTS_DIR,
    AnnouncementError,
    load_announcements,
    render_announcement,
)

# Paths baked into the Docker image (docker/Dockerfile COPY lines). Changes
# elsewhere (docs, tests, workflows) never reach the bot and need no announcement.
DEPLOYED_PATHS = [
    ":(glob)*.py",
    "api",
    "bot",
    "data_provider",
    "src",
    "strategies",
    "apps/dsa-web",
    "docker",
    "requirements.txt",
]
EXCLUDED_PATHS = [":(exclude)bot/announcements"]
# Last deploy before announcements existed; the first announcement starts here.
GENESIS_BASE = "fa0d98709ed3a0a4b287d7f186860d5ba93610c8"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=check
    )


def is_ancestor(older: str, newer: str) -> bool:
    return git("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0


def commit_exists(sha: str) -> bool:
    return git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def deployed_diff_names(base: str, head: str) -> list[str]:
    out = git("diff", "--name-only", f"{base}..{head}", "--", *DEPLOYED_PATHS, *EXCLUDED_PATHS)
    return [line for line in out.stdout.splitlines() if line]


def cmd_prepare() -> int:
    announcements = load_announcements(ANNOUNCEMENTS_DIR)
    base = announcements[-1].head if announcements else git("rev-parse", GENESIS_BASE).stdout.strip()
    head = git("rev-parse", "HEAD").stdout.strip()
    next_id = len(announcements) + 1
    print(f"next file : bot/announcements/{next_id:04d}.md")
    print(f"id        : {next_id}")
    print(f"base      : {base}")
    print(f"head      : {head}   (use the last commit you are announcing; usually HEAD)")
    print()
    print("== net diffstat of deployed code (base..HEAD) ==")
    print(git("diff", "--stat", f"{base}..{head}", "--", *DEPLOYED_PATHS, *EXCLUDED_PATHS).stdout or "(none)")
    print("== commits (context only; describe the NET diff, not this list) ==")
    print(git("log", "--oneline", "--no-merges", f"{base}..{head}", "--", *DEPLOYED_PATHS, *EXCLUDED_PATHS).stdout or "(none)")
    return 0


def cmd_check(require_current: bool) -> int:
    try:
        announcements = load_announcements(ANNOUNCEMENTS_DIR)
    except AnnouncementError as exc:
        print(f"FAIL: {exc}")
        return 1
    if not announcements:
        print("OK: no announcements yet")
        return 0

    errors = []
    if announcements[0].base != GENESIS_BASE:
        errors.append(f"0001.md: base must be the genesis commit {GENESIS_BASE}")
    for a in announcements:
        for label, sha in (("base", a.base), ("head", a.head)):
            if not commit_exists(sha):
                errors.append(f"{a.key}.md: {label} {sha[:7]} is not in this repository")
        if commit_exists(a.base) and commit_exists(a.head):
            if not is_ancestor(a.base, a.head) or a.base == a.head:
                errors.append(f"{a.key}.md: base must be a strict ancestor of head")
            elif not deployed_diff_names(a.base, a.head):
                errors.append(f"{a.key}.md: base..head has no deployed-code changes; nothing to announce")
            if not is_ancestor(a.head, "HEAD"):
                errors.append(f"{a.key}.md: head {a.head[:7]} is not in the current branch history")

    latest = announcements[-1]
    if require_current and not errors:
        pending = deployed_diff_names(latest.head, "HEAD")
        if pending:
            errors.append(
                f"deployed code changed after announcement #{latest.id} head {latest.head[:7]}; "
                f"write announcement #{latest.id + 1} before deploying:\n  " + "\n  ".join(pending)
            )

    if errors:
        print("FAIL:\n- " + "\n- ".join(errors))
        return 1
    embed = render_announcement(latest)
    print(f"OK: {len(announcements)} announcement(s); latest #{latest.id}")
    print()
    print(embed["title"])
    print(embed["description"])
    print(embed["footer"]["text"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="show next id, base and net diff")
    check = sub.add_parser("check", help="validate announcements")
    check.add_argument("--require-current", action="store_true", help="fail if deployed code changed after the latest head")
    args = parser.parse_args()
    if args.command == "prepare":
        return cmd_prepare()
    return cmd_check(args.require_current)


if __name__ == "__main__":
    sys.exit(main())
