"""Release a new version of oxrpy in one step.

    python scripts/release.py 2.6.0            # check everything, bump the version, commit and tag
    python scripts/release.py 2.6.0 --push     # ...then push, which publishes to PyPI, and add
                                               # the GitHub release page (needs the gh CLI)

Before running it, put the release notes under "## Unreleased" at the top of CHANGELOG.md. The
script then:

1. checks you're on main with nothing uncommitted, and the version is newer than the last one
2. sets oxrpy.__version__ and renames "## Unreleased" to "## 2.6.0" in the changelog
3. checks the typed stub is up to date, then runs the tests (with coverage) and mypy
4. commits ("2.6.0") and tags (v2.6.0)

If any check fails, nothing is committed: fix it, `git checkout -- .` to undo the bump, and run
it again. Pushing the tag is what publishes: GitHub Actions tests it again and uploads to PyPI.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "oxrpy" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_RE = re.compile(r'^__version__ = "([^"]+)"', re.M)


def run(*cmd: str, capture: bool = False) -> str:
    print("  $", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)
    if result.returncode:
        if capture:
            print(result.stdout, result.stderr, file=sys.stderr)
        sys.exit(f"Stopped: {' '.join(cmd)} failed")
    return result.stdout if capture else ""


def parse(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"{version!r} isn't a version like 2.6.0")
    return tuple(int(part) for part in version.split("."))


def notes(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return (m.group(1).strip() if m else "") + (
        f"\n\n```\npip install -U oxrpy\n```\n\n"
        f"[oxrpy {version} on PyPI](https://pypi.org/project/oxrpy/{version}/) · [Documentation](https://oxrpy.org)\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="the new version, e.g. 2.6.0")
    parser.add_argument("--push", action="store_true", help="push the commit and tag (publishes), and add the release page")
    args = parser.parse_args()
    version = args.version.removeprefix("v")

    print("Checking")
    current = VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    assert current, "no __version__ in oxrpy/__init__.py"
    if parse(version) <= parse(current.group(1)):
        sys.exit(f"{version} isn't newer than the current {current.group(1)}")
    if run("git", "status", "--porcelain", capture=True).strip():
        sys.exit("There are uncommitted changes: commit or stash them first")
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True).strip()
    if branch != "main":
        sys.exit(f"You're on {branch!r}: release from main")
    if run("git", "tag", "--list", f"v{version}", capture=True).strip():
        sys.exit(f"v{version} is already tagged")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    unreleased = re.search(r"^## Unreleased\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if not unreleased or not unreleased.group(1).strip():
        sys.exit('Put the release notes under "## Unreleased" at the top of CHANGELOG.md first')

    print(f"Bumping {current.group(1)} -> {version}")
    INIT.write_text(VERSION_RE.sub(f'__version__ = "{version}"', INIT.read_text(encoding="utf-8"), count=1),
                    encoding="utf-8", newline="\n")
    CHANGELOG.write_text(changelog.replace("## Unreleased\n", f"## {version}\n", 1), encoding="utf-8", newline="\n")

    print("Testing")
    python = sys.executable
    run(python, "scripts/gen_signatures.py", "--check")
    run(python, "-m", "pytest", "-q", "--cov=oxrpy", "--cov-report=term:skip-covered")
    run(python, "-m", "mypy", "oxrpy")

    print("Committing")
    run("git", "add", str(INIT.relative_to(ROOT)), str(CHANGELOG.relative_to(ROOT)))
    run("git", "commit", "-m", version)
    run("git", "tag", "-a", f"v{version}", "-m", f"oxrpy {version}")

    if not args.push:
        print(f"\nReady. To publish: git push origin main v{version}")
        print(f"(or run this again with --push next time)")
        return
    print("Pushing (GitHub Actions tests it again and publishes to PyPI)")
    run("git", "push", "origin", "main", f"v{version}")
    if shutil.which("gh"):
        notes_file = ROOT / ".release-notes.md"
        notes_file.write_text(notes(version), encoding="utf-8")
        try:
            run("gh", "release", "create", f"v{version}", "--title", f"V{version}", "--notes-file", str(notes_file))
        finally:
            notes_file.unlink(missing_ok=True)
    else:
        print("No gh CLI, so add the release page on GitHub yourself")
    print(f"\nDone: v{version} is on its way to PyPI. Watch it at https://github.com/BLK-TTAUDI/OXRPY/actions")


if __name__ == "__main__":
    main()
