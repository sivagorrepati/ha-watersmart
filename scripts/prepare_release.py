"""Prepare GitHub Actions outputs without interpolating release notes into shell."""

import json
import os
import re
import subprocess
from pathlib import Path

from scripts.build_release import ROOT, VERSION_PATTERN


def normalize_legacy_tags() -> None:
    """Create runner-local aliases so semantic-release recognizes older v tags."""
    tags = set(
        subprocess.check_output(
            ["git", "tag", "--list"], cwd=ROOT, text=True
        ).splitlines()
    )
    for tag in sorted(tags):
        if re.fullmatch("v" + VERSION_PATTERN, tag) and tag[1:] not in tags:
            subprocess.check_call(["git", "tag", tag[1:], f"{tag}^{{}}"], cwd=ROOT)


def main() -> None:
    first_release = os.environ["HAS_RELEASE"] == "false"
    requested = os.environ.get("REQUESTED_VERSION", "").strip()
    version = requested or (
        json.loads(
            (ROOT / "custom_components/ha_watersmart/manifest.json").read_text()
        )["version"]
        if first_release
        else os.environ.get("NEXT_VERSION", "")
    )
    if not version:
        print("No releasable changes since the last tag.")
        return
    if not re.fullmatch(VERSION_PATTERN, version):
        raise ValueError("Release version must use MAJOR.MINOR.PATCH")
    if requested:
        tags = subprocess.check_output(
            ["git", "tag", "--merged", "HEAD", "--list"],
            cwd=ROOT,
            text=True,
        ).splitlines()
        released = [
            (tuple(map(int, tag.removeprefix("v").split("."))), tag)
            for tag in tags
            if re.fullmatch("v?" + VERSION_PATTERN, tag)
        ]
        if released and tuple(map(int, version.split("."))) <= max(released)[0]:
            raise ValueError("Requested version must be newer than the last release")
        if subprocess.check_output(
            ["git", "tag", "--list", version, f"v{version}"], cwd=ROOT, text=True
        ).strip():
            raise ValueError("Requested release tag already exists")
    notes = (
        (ROOT / "docs/releases/0.1.0.md").read_text()
        if first_release
        else os.environ.get("RELEASE_NOTES", "")
    )
    if requested and not first_release:
        last = max(released)[1] if released else None
        commits = subprocess.check_output(
            ["git", "log", "--format=- %s (%h)", f"{last}..HEAD" if last else "HEAD"],
            cwd=ROOT,
            text=True,
        )
        notes = f"# HA WaterSmart {version}\n\n{commits}"
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    (output / "release-notes.md").write_text(notes)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"version={version}\n")


if __name__ == "__main__":
    main()
