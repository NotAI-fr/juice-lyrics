from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Click, Resize
from textual.message import Message
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

_SECTIONS = (
    ("dashboard", "1 Dashboard"),
    ("browse", "2 Browse"),
    ("library", "3 Library"),
    ("downloads", "4 Downloads"),
    ("settings", "5 Settings"),
)


class NavigationItem(Static):
    """Lightweight mouse navigation without themed button state styling."""

    can_focus = False

    class Activated(Message):
        def __init__(self, item: NavigationItem) -> None:
            self.item = item
            super().__init__()

    def __init__(self, label: str, section: str) -> None:
        super().__init__(label, id=f"nav-{section}", markup=False)
        self.section = section

    def on_click(self, event: Click) -> None:
        self.post_message(self.Activated(self))


class HubScreen(Screen[None]):
    """Shared persistent application chrome for primary screens."""

    def __init__(self, section: str, title: str) -> None:
        super().__init__(id=f"screen-{section}")
        self.section = section
        self.title = title

    def compose_content(self) -> Iterable[Widget]:
        return ()

    def compose(self) -> ComposeResult:
        yield Static("999  ·  Juice WRLD Music Hub", id="brand")
        with Horizontal(id="primary-navigation"):
            for section, label in _SECTIONS:
                current = section == self.section
                item = NavigationItem(f"[{label}]" if current else label, section)
                if current:
                    item.add_class("-current")
                yield item
        with Container(id="screen-content"):
            yield Static(self.title, id="screen-title")
            yield from self.compose_content()
        yield Static("1–5 Switch section   r Refresh   ? Help   q Quit", id="status-footer")

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < 70, "-narrow")
        self.set_class(event.size.height < 30, "-short")
