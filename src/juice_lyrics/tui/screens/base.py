from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Resize
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Static

_SECTIONS = (
    ("dashboard", "1 Dashboard"),
    ("browse", "2 Browse"),
    ("library", "3 Library"),
    ("downloads", "4 Downloads"),
    ("settings", "5 Settings"),
)


class HubScreen(Screen[None]):
    """Shared persistent application chrome for primary screens."""

    def __init__(self, section: str, title: str) -> None:
        super().__init__(id=f"screen-{section}")
        self.section = section
        self.title = title

    def compose_content(self) -> Iterable[Widget]:
        return ()

    def compose(self) -> ComposeResult:
        yield Static("999\nJuice WRLD Music Hub", id="brand")
        with Horizontal(id="primary-navigation"):
            for section, label in _SECTIONS:
                button = Button(label, id=f"nav-{section}")
                if section == self.section:
                    button.add_class("-active")
                yield button
        with Container(id="screen-content"):
            yield Static(self.title, id="screen-title")
            yield from self.compose_content()
        yield Static("1–5 Navigate   Tab Focus   r Refresh   ? Help   q Quit", id="status-footer")

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < 70, "-narrow")
