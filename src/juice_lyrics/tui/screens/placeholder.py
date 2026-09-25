from __future__ import annotations

from collections.abc import Iterable

from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Static

from .base import HubScreen


class PlaceholderScreen(HubScreen):
    """Navigable, explicit placeholder for a planned product section."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__(title.lower(), title)
        self.message = message

    def compose_content(self) -> Iterable[Widget]:
        with Container(id="placeholder-panel"):
            yield Static(self.message, id="placeholder-message", markup=False)
            yield Static("This early TUI shell is read-only.", markup=False)
