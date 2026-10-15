"""Opt-in now playing and recent calls in the Textual client (fakes only)."""
from __future__ import annotations

from blueferry import phone_overview as overview
from blueferry.client import BackendError
from blueferry.models import BackendStatus, CallHistoryEntry
from blueferry.tui import BlueFerryApp, TuiState
from blueferry.tui_phone import RecentCallsScreen, now_playing_text
from tests.test_tui import _Backend, _run_headless


def _status(**extra) -> BackendStatus:
    return BackendStatus.from_dict(
        {"daemon": True, "map": True, "pbap": True, "ancs": True, **extra}
    )


class _PhoneBackend(_Backend):
    def __init__(self, **extra) -> None:
        super().__init__()
        self.extra = extra
        self.snapshot = {
            "enabled": True,
            "available": True,
            "player": {"state": "playing"},
            "track": {"title": "[b]Song[/b]", "artist": "Band\x1b[31m"},
            "supported_commands": ["pause", "previous"],
        }
        self.now_playing_calls = 0
        self.commands: list[str] = []
        self.history_calls: list[int] = []
        self.history: list[CallHistoryEntry] = [
            CallHistoryEntry("missed", "2026-10-01T10:00:00+02:00", "+41790000000",
                             name="[@click=app.quit]Ana[/]"),
            CallHistoryEntry("outgoing", "2026-10-01T09:00:00+02:00", "+41790000001"),
        ]

    def status(self) -> BackendStatus:  # type: ignore[override]
        return _status(**self.extra)

    def now_playing(self) -> dict:
        self.now_playing_calls += 1
        return self.snapshot

    def send_media_command(self, command: str) -> None:
        self.commands.append(command)

    def call_history(self, limit: int = 200) -> list[CallHistoryEntry]:
        self.history_calls.append(limit)
        return self.history


async def _until(pilot, condition) -> None:
    for _attempt in range(40):
        if condition():
            return
        await pilot.pause(0.05)
    assert condition()


def test_now_playing_text_renders_iphone_text_as_plain_text() -> None:
    view = overview.now_playing({
        "available": True,
        "player": {"state": "paused"},
        "track": {"title": "[b]x[/b]\nnext"},
        "supported_commands": ["play", "next"],
    })
    text = now_playing_text(view)
    assert text.plain == "⏸  [b]x[/b] next   p ]"
    assert now_playing_text(overview.now_playing(None)).plain == ""


def test_media_line_and_keys_follow_the_opt_in_and_supported_commands() -> None:
    backend = _PhoneBackend(media_control_enabled=True)

    async def scenario() -> None:
        app = BlueFerryApp(TuiState(backend), monitor_factory=lambda: None)
        async with app.run_test(size=(120, 36)) as pilot:
            line = app.query_one("#now-playing")
            await _until(pilot, lambda: line.display)
            assert "[b]Song[/b] — Band" in line.render().plain
            assert "\x1b" not in line.render().plain

            await pilot.press("p")
            await pilot.press("left_square_bracket")
            await _until(pilot, lambda: len(backend.commands) == 2)
            # The phone does not offer next, so nothing is sent.
            await pilot.press("right_square_bracket")
            await pilot.pause(0.1)
            assert backend.commands == ["toggle", "previous"]

    _run_headless(scenario())


def test_media_stays_hidden_and_silent_without_the_opt_in() -> None:
    backend = _PhoneBackend()

    async def scenario() -> None:
        app = BlueFerryApp(TuiState(backend), monitor_factory=lambda: None)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("p")
            await pilot.pause(0.1)
            assert app.query_one("#now-playing").display is False
            assert backend.now_playing_calls == 0
            assert backend.commands == []

    _run_headless(scenario())


def test_media_failure_hides_the_line() -> None:
    class Failing(_PhoneBackend):
        def now_playing(self) -> dict:
            raise BackendError("no media service")

    backend = Failing(media_control_enabled=True)

    async def scenario() -> None:
        app = BlueFerryApp(TuiState(backend), monitor_factory=lambda: None)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.3)
            assert app.query_one("#now-playing").display is False
            assert app.now_playing.visible is False

    _run_headless(scenario())


def test_recent_calls_screen_lists_calls_as_plain_text() -> None:
    backend = _PhoneBackend(call_history_enabled=True)

    async def scenario() -> None:
        app = BlueFerryApp(TuiState(backend), monitor_factory=lambda: None)
        async with app.run_test(size=(120, 36)) as pilot:
            await _until(pilot, lambda: app.state.status.extra.get("call_history_enabled"))
            await pilot.press("h")
            assert isinstance(app.screen, RecentCallsScreen)
            body = app.screen.query_one("#recent-calls-list")
            await _until(pilot, lambda: "Ana" in body.render().plain)
            plain = body.render().plain
            assert "[@click=app.quit]Ana[/]  Missed · +41790000000" in plain
            assert "+41790000001  Outgoing" in plain
            assert backend.history_calls == [100]

            await pilot.press("m")
            assert "+41790000001" not in body.render().plain
            await pilot.press("escape")
            assert not isinstance(app.screen, RecentCallsScreen)

    _run_headless(scenario())


def test_recent_calls_need_the_opt_in() -> None:
    backend = _PhoneBackend()

    async def scenario() -> None:
        app = BlueFerryApp(TuiState(backend), monitor_factory=lambda: None)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("h")
            await pilot.pause(0.1)
            assert not isinstance(app.screen, RecentCallsScreen)
            assert backend.history_calls == []

    _run_headless(scenario())
