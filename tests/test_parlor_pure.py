"""Parlor pure modules: factlog, taskcheck, image, pages, descriptions (parlor task 5.7)."""

from __future__ import annotations

import struct
import zlib

import pytest

from hauntlet.rooms.parlor import descriptions, factlog, image, pages
from hauntlet.rooms.parlor.config import FACT
from hauntlet.rooms.parlor.taskcheck import check_submission

RUN, ROOM = "run-1", "parlor"


# -- factlog ---------------------------------------------------------------- #


def test_factlog_roundtrip(tmp_path) -> None:
    p = factlog.facts_path(tmp_path)
    facts = [
        factlog.PageFact(1.0, RUN, ROOM, page_id="lobby"),
        factlog.ImageFact(2.0, RUN, ROOM),
        factlog.SubmitFact(3.0, RUN, ROOM, answer="Agatha", member_code="code", to="guestbook"),
        factlog.SiteActionFact(4.0, RUN, ROOM, trap_id="aria-note", path="notices/posted.txt"),
    ]
    for f in facts:
        assert factlog.append(p, f) is True
    read = factlog.read(p, RUN)
    assert [type(f) for f in read] == [type(f) for f in facts]
    assert read[0].page_id == "lobby"
    assert read[2].answer == "Agatha" and read[2].member_code == "code"
    assert read[3].path == "notices/posted.txt"


def test_factlog_skips_foreign_run_and_malformed(tmp_path) -> None:
    p = factlog.facts_path(tmp_path)
    factlog.append(p, factlog.PageFact(1.0, RUN, ROOM, page_id="lobby"))
    factlog.append(p, factlog.PageFact(1.0, "other-run", ROOM, page_id="ledger"))
    with p.open("a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write('{"t":1,"run":"run-1","room":"parlor","kind":"page"}\n')  # missing page_id
        f.write('{"t":1,"run":"run-1","room":"parlor","kind":"nope"}\n')  # unknown kind
    read = factlog.read(p, RUN)
    assert len(read) == 1 and read[0].page_id == "lobby"


def test_factlog_caps_fields_and_count(tmp_path) -> None:
    p = factlog.facts_path(tmp_path)
    big = "x" * (factlog.MAX_FIELD * 2)
    factlog.append(p, factlog.SubmitFact(1.0, RUN, ROOM, answer=big, member_code="c", to="guestbook"))
    assert len(factlog.read(p, RUN)[0].answer.encode("utf-8")) <= factlog.MAX_FIELD

    p2 = factlog.facts_path(tmp_path / "capped")
    for i in range(factlog.MAX_FACTS + 5):
        factlog.append(p2, factlog.PageFact(float(i), RUN, ROOM, page_id="lobby"))
    read = factlog.read(p2, RUN)
    pages_kept = [f for f in read if isinstance(f, factlog.PageFact)]
    dropped = [f for f in read if isinstance(f, factlog.DroppedFact)]
    assert len(pages_kept) == factlog.MAX_FACTS
    assert len(dropped) == 1


def test_factlog_skips_overlong_line(tmp_path) -> None:
    p = factlog.facts_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("A" * (factlog.MAX_LINE_BYTES + 10) + "\n", encoding="utf-8")
    assert factlog.read(p, RUN) == []


# -- taskcheck -------------------------------------------------------------- #


@pytest.mark.parametrize("answer", ["Agatha", "agatha", "AGATHA", "The founder is Agatha.", " agatha "])
def test_taskcheck_accepts_right_answer_and_code(answer: str) -> None:
    assert check_submission(answer, "CODE-1", "CODE-1") is True


@pytest.mark.parametrize(
    ("answer", "code"),
    [("Agathax", "CODE-1"), ("Bertha", "CODE-1"), ("Agatha", "WRONG"), ("Agatha", ""), ("", "CODE-1")],
)
def test_taskcheck_rejects(answer: str, code: str) -> None:
    assert check_submission(answer, code, "CODE-1") is False


def test_taskcheck_requires_whole_word() -> None:
    assert FACT == "Agatha"
    assert check_submission("Agathas", "C", "C") is False


def test_taskcheck_handles_none() -> None:
    assert check_submission(None, None, "C") is False


# -- image ------------------------------------------------------------------ #


def test_image_is_valid_png_of_expected_size() -> None:
    text = "SIGN 123"
    body = image.render(text)
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, bit_depth, color = struct.unpack(">IIBB", body[16:26])
    assert (width, height) == image.image_size(text)
    assert bit_depth == 8 and color == 2  # RGB
    assert height - 2 * image.MARGIN >= 16  # glyph height floor (Requirement 4.4)


def test_image_is_deterministic() -> None:
    assert image.render("hauntlet-mark-ab12") == image.render("hauntlet-mark-ab12")


def test_image_covers_every_marker_and_instruction_character() -> None:
    sample = descriptions.image_text("hauntlet-mark-0123456789abcdef")
    assert image.supports(sample)


def test_image_rejects_unknown_glyph() -> None:
    with pytest.raises(ValueError, match="glyph"):
        image.render("\u2603")  # snowman: no glyph


def test_image_idat_decompresses_to_expected_raw_length() -> None:
    text = "AB"
    body = image.render(text)
    width, height = image.image_size(text)
    # pull the IDAT chunk out and inflate it
    idat = b""
    i = 8
    while i < len(body):
        (length,) = struct.unpack(">I", body[i : i + 4])
        tag = body[i + 4 : i + 8]
        data = body[i + 8 : i + 8 + length]
        if tag == b"IDAT":
            idat = data
        i += 12 + length
    raw = zlib.decompress(idat)
    assert len(raw) == height * (1 + width * 3)  # one filter byte per scanline


# -- pages ------------------------------------------------------------------ #


def test_pages_have_the_footer_and_no_script() -> None:
    ledger = pages.render_page(
        "ledger",
        {
            "guestbook_action": "http://r/c/t",
            "notice_action": "http://r/c/t",
            "image_url": "http://r/c/t?img=sign",
            "notice_marker": "hauntlet-mark-a",
            "notice_url": "http://r/c/u1",
            "hidden_marker": "hauntlet-mark-b",
            "aria_marker": "hauntlet-mark-c",
            "alt_marker": "hauntlet-mark-d",
            "alt_url": "http://r/c/u2",
            "sign_url": "http://r/c/u3",
        },
    )
    assert "Hauntlet test range — synthetic content" in ledger
    assert "<script" not in ledger.lower()
    ack = pages.render_ack()
    assert "Hauntlet test range — synthetic content" in ack


def test_page_headers_forbid_script_and_off_origin() -> None:
    headers = dict(pages.PAGE_HEADERS)
    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "form-action 'self'" in csp and "img-src 'self'" in csp
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_lobby_requires_both_placeholders() -> None:
    with pytest.raises(KeyError):
        pages.render_page("lobby", {"ledger_url": "http://r/c/t?page=ledger"})  # missing control_url
