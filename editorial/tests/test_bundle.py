import pytest

from conftest import BUNDLE
from news_editorial.bundle import BundleError, load_bundle


def test_bundle_loads_and_verifies_manifest():
    bundle = load_bundle(BUNDLE)
    assert bundle.manifest["article_count"] == len(bundle.articles) == 254
    assert bundle.manifest["appearance_count"] == len(bundle.appearances) == 838
    assert bundle.manifest_sha256.startswith("sha256:")
    assert bundle.window == ("2026-09-12T08:00:00.000000Z", "2026-09-15T08:00:00.000000Z")


def test_tampered_bundle_is_refused(tmp_path):
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy)
    with (copy / "articles.jsonl").open("a", encoding="utf8") as handle:
        handle.write("\n")
    with pytest.raises(BundleError) as info:
        load_bundle(copy)
    assert "articles.jsonl" in str(info.value)


def test_unsupported_schema_version_is_refused(tmp_path):
    import json
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy)
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["schema_version"] = 2
    (copy / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        load_bundle(copy)
