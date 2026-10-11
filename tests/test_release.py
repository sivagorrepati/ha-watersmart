"""Check that release archives are installable and contain only intended files."""

import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import build_release, prepare_release


def test_component_manifest_and_display_names_match():
    component = build_release.COMPONENT
    manifest = json.loads((component / "manifest.json").read_text())
    assert manifest["domain"] == component.name == "ha_watersmart"
    assert manifest["name"] == "HA WaterSmart"
    hacs = json.loads((build_release.ROOT / "hacs.json").read_text())
    assert hacs["name"] == manifest["name"]
    for relative in ["strings.json", "translations/en.json"]:
        assert (
            json.loads((component / relative).read_text())["title"] == manifest["name"]
        )


@pytest.fixture
def release_project(tmp_path, monkeypatch):
    component = tmp_path / "custom_components/ha_watersmart"
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
    output = release_project / "dist/ha-watersmart.zip"
    build_release.build_release(output)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "custom_components/ha_watersmart/manifest.json",
            "custom_components/ha_watersmart/__init__.py",
            "custom_components/ha_watersmart/translations/en.json",
            "LICENSE",
        }
        assert archive.testzip() is None


def test_release_keeps_versions_aligned(release_project):
    build_release.build_release(release_project / "ha-watersmart.zip", "0.2.0")
    manifest = json.loads(
        (release_project / "custom_components/ha_watersmart/manifest.json").read_text()
    )
    assert manifest["version"] == "0.2.0"
    assert 'version = "0.2.0"' in (release_project / "pyproject.toml").read_text()


@pytest.mark.parametrize("version", ["bad", "1.2", "01.2.3", "1.2.3\nsecret"])
def test_bad_release_version_does_not_mutate_project(release_project, version):
    project_path = release_project / "pyproject.toml"
    before = project_path.read_text()
    with pytest.raises(ValueError):
        build_release.build_release(release_project / "ha-watersmart.zip", version)
    assert project_path.read_text() == before
    assert not Path(release_project / "ha-watersmart.zip").exists()


@pytest.fixture(params=["v0.1.0", "0.1.0"])
def release_environment(release_project, monkeypatch, request):
    monkeypatch.setattr(prepare_release, "ROOT", release_project)
    monkeypatch.setenv("HAS_RELEASE", "true")
    monkeypatch.setenv("NEXT_VERSION", "")
    monkeypatch.setenv("RELEASE_NOTES", "")
    monkeypatch.setenv("REQUESTED_VERSION", "")
    output = release_project / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=release_project, text=True, stderr=subprocess.STDOUT
        )

    git("init")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "feat: initial integration",
    )
    git("tag", request.param)
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "Fix account discovery (#1)",
    )
    return release_project, output, git


def test_requested_release_includes_nonconventional_commits(
    release_environment, monkeypatch
):
    root, output, _ = release_environment
    monkeypatch.setenv("REQUESTED_VERSION", "0.1.1")
    prepare_release.main()
    assert output.read_text() == "version=0.1.1\n"
    notes = (root / "dist/release-notes.md").read_text()
    assert "Fix account discovery (#1)" in notes
    assert "initial integration" not in notes
    assert (
        json.loads(
            (root / "custom_components/ha_watersmart/manifest.json").read_text()
        )["version"]
        == "0.1.0"
    )


@pytest.mark.parametrize("version", ["bad", "0.1.0", "0.0.9", "1.2.3\nsecret"])
def test_requested_release_rejects_invalid_or_old_versions(
    release_environment, monkeypatch, version
):
    root, output, _ = release_environment
    monkeypatch.setenv("REQUESTED_VERSION", version)
    with pytest.raises(ValueError):
        prepare_release.main()
    assert not output.exists()
    assert not (root / "dist/release-notes.md").exists()


@pytest.mark.parametrize("tag", ["v0.1.1", "0.1.1"])
def test_requested_release_rejects_existing_unmerged_tag(
    release_environment, monkeypatch, tag
):
    _, output, git = release_environment
    original = git("rev-parse", "HEAD").strip()
    git("checkout", "-b", "other-release")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "Other branch release",
    )
    git("tag", tag)
    git("checkout", "--detach", original)
    monkeypatch.setenv("REQUESTED_VERSION", "0.1.1")
    with pytest.raises(ValueError, match="already exists"):
        prepare_release.main()
    assert not output.exists()


def test_semantic_release_uses_calculated_version_and_notes(
    release_environment, monkeypatch
):
    root, output, _ = release_environment
    monkeypatch.setenv("NEXT_VERSION", "0.2.0")
    monkeypatch.setenv("RELEASE_NOTES", "Generated release notes")
    prepare_release.main()
    assert output.read_text() == "version=0.2.0\n"
    assert (root / "dist/release-notes.md").read_text() == "Generated release notes"


def test_empty_semantic_result_does_not_prepare_release(release_environment):
    root, output, _ = release_environment
    prepare_release.main()
    assert not output.exists()
    assert not (root / "dist/release-notes.md").exists()


def test_legacy_alias_keeps_original_commit_and_is_idempotent(release_environment):
    _, _, git = release_environment
    original = git("rev-parse", "HEAD~1").strip()
    prepare_release.normalize_legacy_tags()
    assert git("rev-parse", "0.1.0^{}").strip() == original
    before = git("tag", "--list")
    prepare_release.normalize_legacy_tags()
    assert git("tag", "--list") == before
