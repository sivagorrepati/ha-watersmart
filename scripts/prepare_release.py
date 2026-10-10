"""Prepare GitHub Actions outputs without interpolating release notes into shell."""

import json
import os
import re
from pathlib import Path

from build_release import ROOT, VERSION_PATTERN


def main() -> None:
    first_release = os.environ["HAS_RELEASE"] == "false"
    version = (
        json.loads((ROOT / "custom_components/watersmart/manifest.json").read_text())[
            "version"
        ]
        if first_release
        else os.environ.get("NEXT_VERSION", "")
    )
    if not version:
        print("No releasable changes since the last tag.")
        return
    if not re.fullmatch(VERSION_PATTERN, version):
        raise ValueError("Release version must use MAJOR.MINOR.PATCH")
    notes = (
        (ROOT / "docs/releases/0.1.0.md").read_text()
        if first_release
        else os.environ["RELEASE_NOTES"]
    )
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    (output / "release-notes.md").write_text(notes)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"version={version}\n")


if __name__ == "__main__":
    main()
