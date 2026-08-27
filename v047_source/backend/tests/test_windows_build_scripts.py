from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_powershell_script_has_utf8_bom_for_windows_powershell_51():
    payload = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_bytes()

    assert payload.startswith(b"\xef\xbb\xbf")


def test_inno_setup_script_has_utf8_bom_for_cyrillic_text():
    payload = (ROOT / "build" / "installer.iss").read_bytes()

    assert payload.startswith(b"\xef\xbb\xbf")


def test_inno_installer_never_blocks_on_webview_bootstrapper():
    script = (ROOT / "build" / "installer.iss").read_text(encoding="utf-8-sig")
    run_section = script.split("[Run]", 1)[1]

    assert "MicrosoftEdgeWebView2Setup.exe" not in run_section


def test_windows_build_never_reuses_system_python():
    script = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8-sig")

    assert "py -3.13" not in script
    assert "Get-Command python" not in script
    assert "Start-Process $Installer" not in script
    assert "python-runtime-3.13.15" in script
    assert '& $NuGetExe install python' in script
    assert '-Version $PythonVersion' in script
    assert '-ExcludeVersion' in script


def test_windows_build_validates_runtime_and_recreates_generated_venv():
    script = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8-sig")

    assert 'import logging, re, asyncio, venv' in script
    assert '$BasePython = Join-Path $PythonRuntime "tools\\python.exe"' in script
    assert 'Remove-Item $BuildVenv -Recurse -Force' in script
    assert '& $BasePython -m venv $BuildVenv' in script
    assert '[Net.SecurityProtocolType]::Tls12' in script
    assert '-UseBasicParsing' in script


def test_one_click_windows_build_uses_prebuilt_frontend_and_checks_native_failures():
    script = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8-sig")

    assert "npm" not in script.casefold()
    assert "node-runtime" not in script
    assert 'frontend\\dist\\index.html' in script
    assert "function Assert-LastExit" in script
    for stage in ("nuget python", "pip upgrade", "dependencies", "playwright", "pyinstaller", "inno setup"):
        assert f'Assert-LastExit "{stage}"' in script


def test_windows_build_cleans_inherited_python_environment_variables():
    script = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8-sig")

    assert 'Remove-Item Env:PYTHONHOME' in script
    assert 'Remove-Item Env:PYTHONPATH' in script
    assert '$env:PYTHONNOUSERSITE = "1"' in script


def test_pyinstaller_bundle_contains_database_migrations():
    spec = (ROOT / "build" / "VKOutreachManager.spec").read_text(encoding="utf-8")

    assert '(str(BACKEND / "alembic.ini"), ".")' in spec
    assert '(str(BACKEND / "alembic"), "alembic")' in spec


def test_windows_build_reports_frozen_self_test_traceback():
    script = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8-sig")

    assert "VK_OUTREACH_SELF_TEST_LOG" in script
    assert "function Invoke-FrozenSelfTest" in script
    assert "Get-Content -Raw -Encoding UTF8" in script


def test_windows_build_runs_application_and_browser_self_tests_twice():
    script = (ROOT / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8-sig")

    assert '1..2 | ForEach-Object { Invoke-FrozenSelfTest "--self-test"' in script
    assert '1..2 | ForEach-Object { Invoke-FrozenSelfTest "--browser-self-test"' in script
    assert script.index('Invoke-FrozenSelfTest "--browser-self-test"') < script.index("Compress-Archive")


def test_clickable_windows_launcher_is_ascii_only():
    payload = (ROOT / "build" / "СОБРАТЬ_WINDOWS.cmd").read_bytes()

    launcher = payload.decode("ascii")
    assert "BUILD FAILED" in launcher
    assert "BUILD COMPLETED" in launcher
