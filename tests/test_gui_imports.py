from __future__ import annotations

from pathlib import Path

import pytest


def test_gui_modules_import() -> None:
    pytest.importorskip("tkinter")

    from spatializer.gui import control_panel, device_panel, level_meter, main_window, setup_dialog

    assert setup_dialog.BLACKHOLE_URL.startswith("https://")
    assert len(setup_dialog.STEPS) == 3
    assert hasattr(main_window, "MainWindow")
    assert hasattr(control_panel, "ControlPanel")
    assert hasattr(device_panel, "DevicePanel")
    assert hasattr(level_meter, "LevelMeterWidget")


def test_main_window_builds_without_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tk = pytest.importorskip("tkinter")

    from spatializer.config import AppConfig
    from spatializer.gui import device_panel, main_window

    monkeypatch.setattr(device_panel, "list_devices", lambda: [])
    monkeypatch.setattr(main_window, "detect_blackhole", lambda: 0)
    monkeypatch.setattr(main_window, "show_setup_dialog", lambda _parent: None)

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")

    root.withdraw()
    try:
        app = main_window.MainWindow(root, AppConfig(dataset_root=tmp_path))
        root.update_idletasks()
        assert not app._control.has_datasets()
    finally:
        root.destroy()
