"""Check that every tracked Markdown file's relative .md links resolve to tracked targets.

A link passes only when its target file exists AND is git-tracked. This catches both broken
relative paths and links into files that exist locally but are excluded from publication by
.gitignore — the failure mode of a repository that publishes only selected files from a mostly
ignored docs tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

LINK_PATTERN = re.compile(r"\]\(([^()\s]+?\.md)(#[^()\s]*)?\)")
SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.splitlines()


def find_link_breaks(root: Path, tracked_paths: set[str], tracked_markdown: list[str]) -> list[str]:
    findings: list[str] = []
    for source_rel in tracked_markdown:
        source = root / source_rel
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            findings.append(f"{source_rel}: unreadable ({error})")
            continue
        for number, line in enumerate(lines, start=1):
            for match in LINK_PATTERN.finditer(line):
                raw = match.group(1)
                if SCHEME_PATTERN.match(raw):
                    continue
                target_text = urllib.parse.unquote(raw.split("#", 1)[0])
                resolved = Path(source.parent, target_text).resolve()
                try:
                    repo_relative = resolved.relative_to(root).as_posix()
                except ValueError:
                    findings.append(f"{source_rel}:{number} -> {raw} (escapes the repository)")
                    continue
                if repo_relative not in tracked_paths:
                    state = "missing" if not resolved.is_file() else "exists but not tracked"
                    findings.append(f"{source_rel}:{number} -> {raw} (target {state})")
    return findings


def main() -> int:
    repo_root = Path(git_lines("rev-parse", "--show-toplevel")[0]).resolve()
    tracked_markdown = [p for p in git_lines("ls-files", "*.md") if p]
    tracked_paths = {p.as_posix() for p in map(Path, git_lines("ls-files"))}
    findings = find_link_breaks(repo_root, tracked_paths, tracked_markdown)
    checked = len(tracked_markdown)
    if findings:
        print(f"FAIL: {len(findings)} broken link(s) across {checked} tracked Markdown files:\n")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"OK: {checked} tracked Markdown files; all relative .md links resolve to targets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
