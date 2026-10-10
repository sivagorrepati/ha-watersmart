"""Check that release archives are installable and contain only intended files."""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import build_release


@pytest.fixture
def release_project(tmp_path, monkeypatch):
    component = tmp_path / "custom_components/watersmart"
    component.mkdir(parents=True)
    (component / "manifest.json").write_text(json.dumps({"version": "0.1.0"}))
    (component / "__init__.py").write_text('"""Integration."""\n')
    (component / "translations").mkdir()
    (component / "translations/en.json").write_text("{}")
    (component / "__pycache__").mkdir()
    (component / "__pycache__/sensor.pyc").write_bytes(b"compiled")
    (component / "capture.har").write_text("sensitive capture")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    (tmp_path / "LICENSE").write_text("Apache License 2.0\n")
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "COMPONENT", component)
    return tmp_path


def test_zip_layout_and_exclusions(release_project):
    output = release_project / "dist/watersmart.zip"
    build_release.build_release(output)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "custom_components/watersmart/manifest.json",
            "custom_components/watersmart/__init__.py",
            "custom_components/watersmart/translations/en.json",
            "LICENSE",
        }
        assert archive.testzip() is None


def test_release_keeps_versions_aligned(release_project):
    build_release.build_release(release_project / "watersmart.zip", "0.2.0")
    manifest = json.loads(
        (release_project / "custom_components/watersmart/manifest.json").read_text()
    )
    assert manifest["version"] == "0.2.0"
    assert 'version = "0.2.0"' in (release_project / "pyproject.toml").read_text()


@pytest.mark.parametrize("version", ["bad", "1.2", "01.2.3", "1.2.3\nsecret"])
def test_bad_release_version_does_not_mutate_project(release_project, version):
    project_path = release_project / "pyproject.toml"
    before = project_path.read_text()
    with pytest.raises(ValueError):
        build_release.build_release(release_project / "watersmart.zip", version)
    assert project_path.read_text() == before
    assert not Path(release_project / "watersmart.zip").exists()
