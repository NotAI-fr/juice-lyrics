"""Human-readable keyboard guide for the implemented TUI actions."""

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static


# Keep descriptions here alongside the screen action inventory. The same concise
# labels are reused by screen footers; this is not a second executable keymap.
KEY_GUIDE: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Global", (("1–5", "Switch sections (outside text entry)"),
                ("r", "Refresh current section"), ("?", "Open Help"),
                ("q", "Quit"), ("Esc", "Close dialog or return from details"))),
    ("Browse", (("↑/↓ or j/k", "Move through results"), ("Enter", "Show song details"),
                ("/", "Focus title search; Enter searches"), ("Space", "Mark or unmark song"),
                ("M", "Toggle marks on this page"), ("u", "Clear marks"),
                ("a", "Add current or marked songs to Downloads"),
                ("n / p", "Next / previous catalogue page"),
                ("PgUp/PgDn", "Scroll loaded results"), ("Home/End", "First / last result"))),
    ("Library", (("↑/↓ or j/k", "Select track"), ("Enter", "Track details"),
                 ("/", "Focus track search; Enter filters"), ("s", "Sync Library"),
                 ("a", "Open Library Issues"),
                 ("g", "Show catalogue recordings missing locally"),
                 ("d", "Review duplicate recordings"),
                 ("e", "Review and apply selected metadata repairs"),
                 ("m", "Preview and maintain lyrics"), ("r", "Refresh library"),
                 ("v", "Verify library"), ("b", "Browse backups"),
                 ("p", "Check player integration"), ("l", "Preview selected lyric refresh"),
                 ("c", "Choose and lock a catalogue match"),
                 ("u", "Unlock and clear a manual match"),
                 ("i", "Preview catalogue identity rebuild"),
                 ("PgUp/PgDn", "Scroll tracks or details"), ("Home/End", "First / last track"))),
    ("Missing Library", (("↑/↓ or j/k", "Select missing recording"),
                         ("/", "Filter loaded catalogue recordings"),
                         ("a", "Add selected recording to Downloads"),
                         ("Esc", "Return to Library"))),
    ("Downloads", (("↑/↓ or j/k", "Select queue item"), ("Enter", "Item details"),
                   ("d", "Download selected song"), ("t", "Retry failed song"),
                   ("A", "Download entire queue (confirmation)"),
                   ("x", "Remove selected waiting/failed item"),
                   ("c", "Clear waiting/failed queue (confirmation)"),
                   ("H", "Clear completed history"),
                   ("PgUp/PgDn", "Scroll queue or details"), ("Home/End", "First / last item"))),
    ("Settings", (("↑/↓ or j/k", "Inspect setting"), ("r", "Refresh"),
                  ("PgUp/PgDn", "Scroll settings"), ("Home/End", "First / last setting"))),
    ("Backups", (("↑/↓ or j/k", "Select backup"), ("r", "Review restore confirmation"),
                 ("Esc", "Return to Library"))),
    ("Confirmations", (("y", "Confirm immediately"), ("n / Esc", "Cancel immediately"),
                      ("Enter", "Choose focused action (Cancel initially)"),
                      ("Tab / Shift+Tab / ←/→", "Move between actions"))),
)


def guide_text() -> str:
    return "\n\n".join(
        f"{heading}\n{'─' * len(heading)}\n" + "\n".join(f"{key:<24}{description}" for key, description in rows)
        for heading, rows in KEY_GUIDE
    )


class HelpScreen(ModalScreen[None]):
    """Scrollable, globally available keyboard guide."""

    def compose(self) -> ComposeResult:
        with Container(id="help-dialog"):
            yield Static("Keyboard help", id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(guide_text(), id="help-content", markup=False)
            yield Static("↑↓ / PgUp/PgDn Scroll   Esc Close", id="help-footer", markup=False)

    def on_mount(self) -> None:
        self.query_one("#help-scroll", VerticalScroll).focus()

    def on_key(self, event: Key) -> None:
        if event.key in {"escape", "question_mark", "q"}:
            self.dismiss(None)
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()
