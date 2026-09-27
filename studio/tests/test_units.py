from pathlib import Path

import pytest
from fastapi import HTTPException

from server.security import check_id, safe_join, sanitize_filename, clean_text
from server.timing import compute_timeline
from server.engine import output_geometry


@pytest.mark.parametrize("raw,expected", [
    ("Exterior Shot.MP4", "Exterior Shot.mp4"),
    ("../../etc/passwd.mov", "passwd.mov"),
    ("..\\..\\win.mov", "win.mov"),
    ("a;rm -rf $(x).mp4", "a_rm -rf_x.mp4"),
    ("\x00evil.mp4", "evil.mp4"),
    ("....mp4", "clip.mp4"),
])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_safe_join_blocks_traversal(tmp_path):
    assert safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()
    with pytest.raises(HTTPException):
        safe_join(tmp_path, "../outside")
    with pytest.raises(HTTPException):
        safe_join(tmp_path, "/etc/passwd")


@pytest.mark.parametrize("bad", ["../x", "ABC", "a/b", "", "x" * 60, "p12 34"])
def test_check_id_rejects(bad):
    with pytest.raises(HTTPException):
        check_id(bad)


def test_clean_text_strips_controls():
    assert clean_text("Living\x07 Room\n  ", 50) == "Living Room"
    assert clean_text("a\nb", 50, multiline=True) == "a\nb"


def test_timeline_cuts_dissolves_and_dips():
    segs = [
        {"source_in": 0, "source_out": 7, "transition": "cut"},
        {"source_in": 2, "source_out": 9, "transition": "dissolve", "transition_duration": 1.0},
        {"source_in": 0, "source_out": 5, "transition": "dip_to_black", "transition_duration": 1.0},
    ]
    tl, total = compute_timeline(segs)
    assert [t["output_in"] for t in tl] == [0.0, 6.0, 13.0]
    assert total == 18.0
    # A dissolve is capped at half the shorter neighbouring shot.
    tl, _ = compute_timeline([{"source_in": 0, "source_out": 1, "transition": "cut"},
                              {"source_in": 0, "source_out": 5, "transition": "dissolve", "transition_duration": 3}])
    assert tl[1]["overlap"] == 0.5


@pytest.mark.parametrize("settings_,src,expected", [
    ({"aspect": "source", "resolution": "original"}, (3840, 2160), (3840, 2160)),
    ({"aspect": "source", "resolution": "1080p"}, (3840, 2160), (1920, 1080)),
    ({"aspect": "9:16", "resolution": "1080p"}, (1920, 1080), (1080, 1920)),
    ({"aspect": "1:1", "resolution": "4k"}, (1920, 1080), (2160, 2160)),
    ({"aspect": "16:9", "resolution": "original"}, (1080, 1920), (1920, 1080)),
])
def test_output_geometry(settings_, src, expected):
    assert output_geometry(settings_, {"width": src[0], "height": src[1]}) == expected
