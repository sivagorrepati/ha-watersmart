"""Synchronize versions and package only installable integration files."""

import argparse
import json
import re
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "ha_watersmart"
VERSION_PATTERN = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"


def build_release(output: Path, version: str | None = None) -> None:
    """Create a ZIP that extracts into the Home Assistant config directory."""
    manifest_path = COMPONENT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    project_path = ROOT / "pyproject.toml"
    project_text = project_path.read_text()
    if version is not None:
        if not re.fullmatch(VERSION_PATTERN, version):
            raise ValueError("Release version must use MAJOR.MINOR.PATCH")
        project_text, replaced = re.subn(
            r'(?m)^version = "[^"]+"$', f'version = "{version}"', project_text
        )
        if replaced != 1:
            raise ValueError("Expected exactly one project version")
        manifest["version"] = version
    project = tomllib.loads(project_text)
    if project["project"]["version"] != manifest["version"]:
        raise ValueError("Project and integration versions must match")
    # Validate before mutating either version file.
    if version is not None:
        project_path.write_text(project_text)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json"}:
                archive.write(path, path.relative_to(ROOT).as_posix())
        archive.write(ROOT / "LICENSE", "LICENSE")
    print(f"Built HA WaterSmart {manifest['version']}: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Set the project and manifest versions")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist" / "ha-watersmart.zip"
    )
    arguments = parser.parse_args()
    build_release(arguments.output, arguments.version)
