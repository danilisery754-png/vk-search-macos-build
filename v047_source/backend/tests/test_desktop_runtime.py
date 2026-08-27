import importlib.util
import socket
import sys
from pathlib import Path


def load_desktop_main():
    path = Path(__file__).resolve().parents[2] / "desktop" / "main.py"
    spec = importlib.util.spec_from_file_location("desktop_main", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_find_available_port_returns_bindable_local_port():
    desktop = load_desktop_main()

    port = desktop.find_available_port("127.0.0.1")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_self_test_flag_is_detected_explicitly():
    desktop = load_desktop_main()

    assert desktop.is_self_test(["program.exe", "--self-test"]) is True
    assert desktop.is_self_test(["program.exe"]) is False


def test_browser_self_test_flag_is_detected_explicitly():
    desktop = load_desktop_main()

    assert desktop.is_browser_self_test(["program.exe", "--browser-self-test"]) is True
    assert desktop.is_browser_self_test(["program.exe"]) is False


def test_browser_self_test_is_dispatched_before_the_gui(monkeypatch):
    desktop = load_desktop_main()

    monkeypatch.setattr(sys, "argv", ["program.exe", "--browser-self-test"])
    monkeypatch.setattr(desktop, "run_browser_self_test", lambda: 23)

    assert desktop.main() == 23


def test_self_test_failure_is_written_to_requested_log(monkeypatch, tmp_path):
    desktop = load_desktop_main()
    log_path = tmp_path / "self-test-error.log"

    monkeypatch.setenv("VK_OUTREACH_SELF_TEST_LOG", str(log_path))
    monkeypatch.setattr(sys, "argv", ["program.exe", "--self-test"])

    def fail():
        raise RuntimeError("frozen self-test failed")

    monkeypatch.setattr(desktop, "run_self_test", fail)

    assert desktop.main() == 1
    report = log_path.read_text(encoding="utf-8")
    assert "RuntimeError: frozen self-test failed" in report


def test_frozen_gui_self_test_runs_without_console_streams(monkeypatch):
    desktop = load_desktop_main()

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    assert desktop.run_self_test() == 0
