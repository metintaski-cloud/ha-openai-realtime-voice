"""Notes to GPT Live must stay under its limit of 500 tokens (found 24 Nov 2026: every note
after the code word was rejected). Invented neutral sentences only."""
from app import notes


def test_a_short_note_goes_out_as_it_is():
    assert notes.pieces("Interne Notiz: alles gut.") == ["Interne Notiz: alles gut."]
    assert notes.pieces("   ") == []


def test_a_long_list_is_cut_at_line_ends_and_nothing_is_lost():
    lines = ["Interne Notiz, nicht vorlesen: Liste:"] + [
        f"{i}. Der Garten braucht im Sommer jeden zweiten Tag Wasser, Punkt {i}." for i in range(60)]
    got = notes.pieces("\n".join(lines))
    assert len(got) > 3 and all(len(p) <= notes.NOTE_MAX_CHARS for p in got)
    assert not got[0].startswith("Interne Notiz, nicht vorlesen und nicht erwähnen (Fortsetzung")
    assert got[1].startswith(notes.CONTINUES.format(i=2, n=len(got)))
    assert got[0].endswith(notes.MORE) and not got[-1].endswith(notes.MORE)
    body = "\n".join(p.replace(notes.MORE, "").split("):\n", 1)[-1] if i else p.replace(notes.MORE, "")
                     for i, p in enumerate(got))
    assert [l for l in body.split("\n") if l] == lines


def test_one_long_line_is_cut_at_sentence_ends_and_an_endless_word_hard():
    line = " ".join(f"Satz Nummer {i} erzählt etwas vom Wetter am Fluss." for i in range(80))
    got = notes.pieces(line)
    assert len(got) > 2 and all(len(p) <= notes.NOTE_MAX_CHARS for p in got)
    assert all(p.replace(notes.MORE, "").rstrip().endswith(".") for p in got)
    assert all(len(p) <= notes.NOTE_MAX_CHARS for p in notes.pieces("x" * 5000))
    assert "".join(p.replace(notes.MORE, "").split("):\n", 1)[-1] for p in notes.pieces("x" * 5000)).count("x") == 5000


def test_a_rejected_piece_comes_back_as_two_halves_once():
    sent = notes.Sent()
    text = "\n".join(f"Zeile {i} mit ein paar Worten über den Tag." for i in range(20))
    sent.add("diary_1", "diary", text)
    err = {"type": "error", "error": {"message": "Context append text must not exceed 500 tokens.",
                                      "client_event_id": "diary_1"}}
    prefix, halves = sent.halves(err)
    assert prefix == "diary" and len(halves) >= 2 and all(len(h) < len(text) for h in halves)
    assert sent.halves(err) == ("", [])                       # the same error twice: nothing more
    sent.add("x_1", "x", "kurz")
    assert sent.halves({"error": {"message": "must not exceed", "client_event_id": "x_1"}}) == ("x", [])
    sent.add("y_1", "y", text)
    assert sent.halves({"error": {"message": "quota", "client_event_id": "y_1"}}) == ("", [])


def test_only_the_last_notes_are_kept():
    sent = notes.Sent(keep=3)
    for i in range(5):
        sent.add(f"n_{i}", "n", "text")
    assert list(sent.items) == ["n_2", "n_3", "n_4"]
