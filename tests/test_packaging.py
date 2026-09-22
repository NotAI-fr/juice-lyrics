from __future__ import annotations

from pathlib import Path
import sys
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from juice_lyrics import __version__


def _pyproject() -> dict:
    return tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )


def test_distribution_metadata_has_one_version_authority_and_current_entry_points():
    project = _pyproject()

    assert project["project"]["name"] == "juice-wrld-lyrics"
    assert project["project"]["dynamic"] == ["version"]
    assert "version" not in project["project"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "juice_lyrics.__version__"
    }
    assert __version__ == "1.4.0"
    assert project["project"]["scripts"] == {
        "999": "juice_lyrics.cli:main",
        "juice-lyrics": "juice_lyrics.cli:main",
    }


def test_distribution_metadata_uses_current_license_and_bounded_dependencies():
    project = _pyproject()

    assert project["build-system"]["requires"] == ["setuptools>=77"]
    assert project["project"]["license"] == "MIT"
    assert project["project"]["license-files"] == ["LICENSE"]
    assert project["project"]["dependencies"] == [
        "mutagen>=1.47,<2.0",
        "textual>=1.0,<2.0",
    ]


def test_source_distribution_manifest_excludes_repository_only_material():
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    for required in ("LICENSE", "README.md", "pyproject.toml"):
        assert f"include {required}" in manifest
    assert "recursive-include src *.py" in manifest
    for repository_only in ("docs", "tests"):
        assert f"prune {repository_only}" in manifest
    for handoff in ("AGENTS.md", "PROJECT_CONTEXT.md", ".gitignore"):
        assert f"exclude {handoff}" in manifest
    assert "global-exclude __pycache__" in manifest
    assert "global-exclude *.py[cod]" in manifest


def test_every_python_package_is_under_the_configured_source_tree():
    project = _pyproject()
    source_root = PROJECT_ROOT / project["tool"]["setuptools"]["package-dir"][""]
    configured_root = project["tool"]["setuptools"]["packages"]["find"]["where"]

    assert configured_root == ["src"]
    packages = {
        path.parent.relative_to(source_root).as_posix().replace("/", ".")
        for path in source_root.rglob("__init__.py")
    }
    assert "juice_lyrics" in packages
    assert all(name == "juice_lyrics" or name.startswith("juice_lyrics.") for name in packages)


def test_runtime_sources_do_not_contain_a_checkout_specific_path():
    forbidden = "/home/nobloat/Downloads/juice-lyrics-codex"

    for source in (PROJECT_ROOT / "src" / "juice_lyrics").rglob("*.py"):
        assert forbidden not in source.read_text(encoding="utf-8"), source
