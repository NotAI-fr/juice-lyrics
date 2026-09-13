from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library import matching


BANDIT_RESULTS = [
    {"id": 95074, "name": "Bandit (v1)", "category": "unreleased", "length": "3:33"},
    {"id": 95295, "name": "Bandit (v2)", "category": "unreleased", "length": "3:22"},
    {
        "id": 96405,
        "name": "Bandit (with YoungBoy Never Broke Again)",
        "category": "recording_session",
        "length": "",
    },
    {
        "id": 95296,
        "name": "Bandit (with YoungBoy Never Broke Again) [v1]",
        "category": "unreleased",
        "length": "3:12",
    },
    {
        "id": 95297,
        "name": "Bandit (with YoungBoy Never Broke Again) [v2]",
        "category": "unreleased",
        "length": "3:13",
    },
    {
        "id": 95845,
        "name": "Bandit (with YoungBoy Never Broke Again) [v3]",
        "category": "unsurfaced",
        "length": "",
    },
    {
        "id": 95298,
        "name": "Bandit (with YoungBoy Never Broke Again) [v4]",
        "category": "unreleased",
        "length": "3:12",
    },
    {
        "id": 94107,
        "name": "Bandit (feat. YoungBoy Never Broke Again)",
        "category": "released",
        "length": "3:09",
        "path": (
            "Compilation/1. Released Discography/15. Death Race For Love "
            "(Bonus Track Version)/Bandit (with YoungBoy Never Broke Again).mp3"
        ),
    },
]

TEN_FEET_RESULTS = [
    {
        "id": 94102,
        "name": "10 Feet",
        "category": "released",
        "length": "3:36",
        "path": "Compilation/1. Released Discography/11. Death Race For Love/10 Feet.mp3",
    },
    {"id": 96383, "name": "10 Feet", "category": "recording_session", "length": ""},
    {"id": 95061, "name": "10 Feet (v1)", "category": "unreleased", "length": "3:38"},
    {"id": 95062, "name": "10 Feet (v3)", "category": "unreleased", "length": "3:36"},
    {"id": 94269, "name": "10 Feet (TV Mix) [v1]", "category": "released", "length": "3:36"},
]


def _local(monkeypatch, *, title: str, duration: float, album: str | None) -> Path:
    path = Path("opaque.flac")
    monkeypatch.setattr(matching, "is_tagged_container", lambda value: True)
    monkeypatch.setattr(matching, "tagged_matching_title", lambda value: title)
    monkeypatch.setattr(matching, "local_duration", lambda value: duration)
    monkeypatch.setattr(matching, "local_album", lambda value: album)
    return path


def test_bandit_live_candidate_set_selects_released_recording(monkeypatch):
    path = _local(
        monkeypatch,
        title="Bandit (with YoungBoy Never Broke Again)",
        duration=189.322562,
        album="Death Race For Love (Bonus Track Version)",
    )

    chosen, _, reasons, _ = matching.choose_candidate(
        Settings(), path, BANDIT_RESULTS, "Bandit"
    )
    diagnostics = matching.diagnose_candidates(Settings(), path, BANDIT_RESULTS, "Bandit")
    by_id = {row.song_id: row for row in diagnostics}

    assert chosen is not None and chosen["id"] == 94107
    assert "released (+10)" in reasons
    assert "album/path match (+35)" in reasons
    assert by_id[96405].rejection == "lower-ranked candidate"
    assert by_id[96405].reasons[-1] == "duration unknown (+0)"
    assert by_id[95296].score < by_id[94107].score
    assert by_id[95297].rejection == "known duration outside tolerance"
    assert by_id[95298].score < by_id[94107].score


def test_bandit_feat_and_with_collaboration_forms_share_base_identity():
    assert matching.normalize(matching.strip_feature_credit("Bandit (with YoungBoy)")) == matching.normalize(
        matching.strip_feature_credit("Bandit (feat. YoungBoy)")
    )


def test_ten_feet_live_candidate_set_selects_normal_album_recording(monkeypatch):
    path = _local(
        monkeypatch,
        title="10 Feet",
        duration=212.311927,
        album="Death Race For Love (Bonus Track Version)",
    )

    chosen, _, reasons, _ = matching.choose_candidate(
        Settings(), path, TEN_FEET_RESULTS, "10 Feet"
    )
    diagnostics = matching.diagnose_candidates(Settings(), path, TEN_FEET_RESULTS, "10 Feet")
    by_id = {row.song_id: row for row in diagnostics}

    assert chosen is not None and chosen["id"] == 94102
    assert any(reason.startswith("duration catalogue grace (3.688s delta") for reason in reasons)
    assert "album edition/path match (+30)" in reasons
    assert by_id[96383].reasons[-1] == "duration unknown (+0)"
    assert by_id[96383].score < by_id[94102].score
    assert by_id[95062].eligible is False
    assert by_id[94269].eligible is False
    assert any("candidate-only variant tv mix" in reason for reason in by_id[94269].reasons)


def test_normal_duration_match_scores_more_than_catalogue_grace(monkeypatch):
    path = _local(
        monkeypatch,
        title="Album Song",
        duration=212.311927,
        album="Example Album (Deluxe Edition)",
    )
    normal = {
        "id": 1,
        "name": "Album Song",
        "category": "released",
        "length": "3:35",
        "album": "Example Album (Deluxe Edition)",
    }
    grace = {**normal, "id": 2, "length": "3:36"}

    normal_score, normal_reasons = matching.score_candidate(Settings(), path, normal, "Album Song")
    grace_score, grace_reasons = matching.score_candidate(Settings(), path, grace, "Album Song")

    assert normal_score > grace_score
    assert any(reason.startswith("duration match") for reason in normal_reasons)
    assert any(reason.startswith("duration catalogue grace") for reason in grace_reasons)


@pytest.mark.parametrize(
    "candidate",
    [
        {"id": 1, "name": "Album Song (v3)", "category": "released", "length": "3:36", "album": "Example Album"},
        {"id": 2, "name": "Album Song (TV Mix)", "category": "released", "length": "3:36", "album": "Example Album"},
        {"id": 3, "name": "Album Song", "category": "released", "length": "3:36", "album": "Unrelated Album"},
    ],
)
def test_duration_grace_requires_unversioned_unvaried_album_corroboration(monkeypatch, candidate):
    path = _local(
        monkeypatch,
        title="Album Song",
        duration=212.311927,
        album="Example Album (Bonus Track Version)",
    )

    chosen, _, reasons, _ = matching.choose_candidate(Settings(), path, [candidate], "Album Song")

    assert chosen is None
    assert any(reason.startswith("duration mismatch") for reason in reasons)


def test_album_edition_compatibility_is_recognized_but_arbitrary_parentheticals_are_not(monkeypatch):
    path = _local(
        monkeypatch,
        title="Album Song",
        duration=212.311927,
        album="Example Album (Anniversary Edition)",
    )
    candidate = {"name": "Album Song", "album": "Example Album"}

    assert matching.album_match_kind(path, candidate) == "edition"

    monkeypatch.setattr(matching, "local_album", lambda value: "Example Album")
    assert matching.album_match_kind(
        path, {"name": "Album Song", "album": "Example Album (Deluxe Edition)"}
    ) == "edition"

    monkeypatch.setattr(matching, "local_album", lambda value: "Example Album (Live in London)")
    assert matching.album_match_kind(path, candidate) is None


def test_unknown_duration_can_win_with_overwhelming_unopposed_evidence(monkeypatch):
    path = _local(monkeypatch, title="Rental", duration=180.0, album=None)
    candidate = {
        "id": 1,
        "name": "Rental",
        "category": "recording_session",
        "length": "",
        "path": "opaque.flac",
    }

    chosen, score, reasons, _ = matching.choose_candidate(Settings(), path, [candidate], "Rental")

    assert chosen is candidate
    assert score >= matching.MATCH_THRESHOLD
    assert "duration unknown (+0)" in reasons


def test_same_title_same_duration_candidates_remain_ambiguous(monkeypatch):
    path = _local(monkeypatch, title="Song", duration=180.0, album=None)
    candidates = [
        {"id": 1, "name": "Song", "category": "recording_session", "length": "3:00"},
        {"id": 2, "name": "Song", "category": "recording_session", "length": "3:00"},
    ]

    chosen, _, _, _ = matching.choose_candidate(Settings(), path, candidates, "Song")
    diagnostics = matching.diagnose_candidates(Settings(), path, candidates, "Song")

    assert chosen is None
    assert all(row.rejection == "ambiguous within safety margin" for row in diagnostics)


def test_known_duration_outside_tolerance_remains_ineligible(monkeypatch):
    path = _local(monkeypatch, title="Song", duration=180.0, album=None)
    candidate = {"id": 1, "name": "Song", "category": "released", "length": "4:00"}

    chosen, _, _, _ = matching.choose_candidate(Settings(), path, [candidate], "Song")
    diagnostic = matching.diagnose_candidates(Settings(), path, [candidate], "Song")[0]

    assert chosen is None
    assert diagnostic.eligible is False
    assert diagnostic.rejection == "known duration outside tolerance"


@pytest.mark.parametrize("suffix", [".mp3", ".flac", ".m4a"])
def test_supported_formats_share_identical_ranking_semantics(monkeypatch, suffix):
    path = _local(monkeypatch, title="10 Feet", duration=216.0, album="Death Race For Love")
    path = path.with_suffix(suffix)

    chosen, score, reasons, _ = matching.choose_candidate(
        Settings(), path, TEN_FEET_RESULTS, "10 Feet"
    )

    assert chosen is not None and chosen["id"] == 94102
    assert score > 0
    assert "album/path match (+35)" in reasons
