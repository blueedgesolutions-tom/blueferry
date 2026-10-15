"""blueferry-tray: pure presenter logic plus an offscreen smoke test."""
from __future__ import annotations

import importlib.util
import os
import subprocess  # nosec B404 - runs the smoke script in a fresh process
import sys
import textwrap
from pathlib import Path

import pytest

from blueferry.models import BackendStatus, Thread
from blueferry.qt import tray_presenter as presenter

ROOT = Path(__file__).resolve().parents[1]

# The smoke tests start the real tray in a child process. Distributions
# without PySide6 (the Ubuntu package build) skip them; the presenter tests
# stay pure Python.
needs_pyside6 = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="PySide6 is not installed",
)


def _thread(*read_flags: bool, outgoing: bool = False) -> Thread:
    return Thread.from_dict({
        "key": "t",
        "messages": [
            {"handle": str(index), "body": "", "read": read, "outgoing": outgoing}
            for index, read in enumerate(read_flags)
        ],
    })


def test_unread_total_counts_incoming_unread_messages_only() -> None:
    threads = [_thread(False, True, False), _thread(False, outgoing=True), _thread(True)]
    assert presenter.unread_total(threads) == 2
    assert presenter.unread_total([]) == 0


@pytest.mark.parametrize(("count", "text"), [(0, ""), (-1, ""), (1, "1"), (99, "99"), (100, "99+")])
def test_badge_text(count: int, text: str) -> None:
    assert presenter.badge_text(count) == text


def test_tooltip_lists_connection_battery_signal_network_and_unread() -> None:
    assert presenter.tooltip(None, 0) == "BlueFerry service is not running"
    assert presenter.tooltip(None, 0, "needs update") == "needs update"
    status = BackendStatus.from_dict({
        "map": True, "phone_battery_level": 87, "phone_battery_source": "gatt",
        "phone_signal_strength": 60, "phone_network_name": "Sunrise",
        "phone_network_status": "registered",
    })
    assert presenter.tooltip(status, 3).splitlines() == [
        "iPhone connected", "Battery: 87 %", "Signal: 60 %", "Network: Sunrise",
        "3 unread messages",
    ]
    offline = BackendStatus.from_dict({"phone_battery_level": 40, "phone_battery_source": "hfp"})
    assert presenter.tooltip(offline, 1).splitlines() == [
        "iPhone offline", "Battery: about 40 %", "1 unread message",
    ]
    connecting = BackendStatus.from_dict({"initializing": True})
    assert presenter.tooltip(connecting, 0) == "Connecting…"


_SMOKE = textwrap.dedent("""
    import json, sys, time
    from PySide6.QtDBus import QDBusConnection
    from PySide6.QtWidgets import QApplication
    from blueferry.protocol import MESSAGES_API_VERSION
    from blueferry.qt.tray import TrayController, badged_icon, phone_icon

    app = QApplication([])
    address = sys.argv[1]
    bus = (QDBusConnection.connectToBus(address, "tray-smoke") if address
           else QDBusConnection("not-connected"))
    launches = []
    tray = TrayController(bus, launch=lambda: launches.append(1) or True)
    tray.tray.setVisible(True)  # so hiding must come from the bus reply
    tray.start()
    for _ in range(100):  # the ListActivatableNames reply is asynchronous
        app.processEvents()
        time.sleep(0.01)
    # Private test bus: BlueFerry is not activatable, so the icon hides.
    # No bus at all: unknown, so it stays.
    assert tray.tray.isVisible() is (not address), tray.tray.isVisible()
    # No daemon on the bus: offline, and nothing was activated.
    assert tray.status is None, tray.status
    assert tray.tray.toolTip() == "BlueFerry service is not running", tray.tray.toolTip()

    tray.apply_status(json.dumps({
        "api_version": MESSAGES_API_VERSION, "map": True,
        "phone_battery_level": 87, "phone_battery_source": "gatt",
    }))
    tray.apply_threads(json.dumps([{"key": "a", "messages": [
        {"handle": "1", "body": "", "read": False},
        {"handle": "2", "body": "", "read": False}]}]))
    lines = tray.tray.toolTip().splitlines()
    assert lines == ["iPhone connected", "Battery: 87 %", "2 unread messages"], lines
    texts = [action.text() for action in tray.menu.actions() if not action.isSeparator()]
    assert texts[0] == "Open BlueFerry" and texts[-1] == "Quit", texts

    tray.apply_status(json.dumps({"api_version": 0}))
    assert "needs an update" in tray.tray.toolTip()

    tray.open_app()  # no Qt client registered: start one
    assert launches == [1]

    badge = badged_icon(phone_icon(), "3").pixmap(64, 64).toImage()
    red = badge.pixelColor(56, 6)
    assert red.red() > 180 and red.green() < 120, red.name()
    assert badged_icon(phone_icon(), "").pixmap(64, 64).toImage().pixelColor(63, 0).alpha() == 0
    tray.close()
    print("SMOKE-OK")
""")


@needs_pyside6
@pytest.mark.parametrize("use_private_bus", [False, True])
def test_tray_smoke_offscreen(use_private_bus: bool) -> None:
    address = os.environ.get("BLUEFERRY_TEST_DBUS_ADDRESS", "") if use_private_bus else ""
    if use_private_bus and not address:
        pytest.skip("needs the private dbus-run-session test bus")
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": str(ROOT / "src"),
        "LANGUAGE": "C",
    }
    if not use_private_bus:
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/tmp/blueferry-tests-no-live-bus"
    result = subprocess.run(  # nosec B603 - fixed interpreter and script
        [sys.executable, "-c", _SMOKE, address],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )
    assert "SMOKE-OK" in result.stdout, result.stdout + result.stderr
