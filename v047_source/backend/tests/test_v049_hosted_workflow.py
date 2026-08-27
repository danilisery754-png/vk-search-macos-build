from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "build-v049-macos-arm64.yml"


def test_v049_release_workflow_uses_free_github_hosted_arm64_mac_runner():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "runs-on: macos-14" in text
    assert "self-hosted" not in text
    assert "ubuntu-" not in text
    assert "windows-" not in text


def test_v049_release_workflow_restores_assets_and_runs_full_verification_before_release():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Restore generated image assets" in text
    assert "backend/tests/test_v049_behavior.py" in text
    assert "backend/tests/test_v049_hosted_workflow.py" in text
    assert "backend/tests/test_v049_self_hosted_workflow.py" not in text
    assert "backend/tests/test_v049_static_assets.py" in text
    assert "backend/tests/test_v049_archive_sync.py" in text
    assert "backend/tests/test_v049_routes.py" in text
    assert "backend/tests/test_v049_migration_upgrade.py" in text
    assert "backend/tests/test_v049_deleted_preview_runtime.py" in text
    assert "backend/tests/test_v049_desktop_layout_contract.py" in text
    assert "backend/tests/test_v048_behavior.py" in text
    assert "npm test" in text
    assert "npm run typecheck" in text
    assert "npm run build" in text
    assert "bash build/BUILD_MACOS.sh" in text
    assert "VK_Search_0.4.9_macOS_arm64.dmg" in text
    assert "uploads.github.com" in text
    assert "http.client.HTTPSConnection" in text
    assert "gh release" not in text
    assert "actions/upload-artifact" not in text


def test_v049_workflow_only_rewrites_lockfile_version_metadata_before_npm_ci():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "npm install --package-lock-only" not in text
    assert "lock.version = '0.4.9'" in text
    assert "lock.packages[''].version = '0.4.9'" in text
    assert text.index("lock.version = '0.4.9'") < text.index("npm ci")
