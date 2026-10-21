"""Select a release only when the manifest version increases across a push."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def version_parts(version: str) -> tuple[int, ...]:
    """Parse stable and a/b/rc versions in release order."""
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:(a|b|rc)(0|[1-9][0-9]*))?",
        version,
    )
    if match is None:
        message = f"Unsupported manifest version: {version}"
        raise ValueError(message)
    return (
        *(int(part) for part in match.groups()[:3]),
        {"a": 0, "b": 1, "rc": 2, None: 3}[match.group(4)],
        int(match.group(5) or 0),
    )


def release_tag(previous: str, current: str) -> str:
    """Return no tag for ordinary commits and reject version rollbacks."""
    if current == previous:
        return ""
    if version_parts(current) <= version_parts(previous):
        raise ValueError("The manifest version must increase for a release")
    return f"v{current}"


def main() -> None:
    """Compare the push's starting revision with the checked-out commit."""
    manifest = Path(sys.argv[1])
    before = os.environ["BEFORE_SHA"]
    previous = json.loads(
        subprocess.check_output(
            ["git", "show", f"{before}:{manifest.as_posix()}"],
        )
    )["version"]
    current = json.loads(manifest.read_text())["version"]
    tag = release_tag(previous, current)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"tag={tag}\n")
    print(f"Release requested: {tag}" if tag else "No version change; no release")


if __name__ == "__main__":
    main()
