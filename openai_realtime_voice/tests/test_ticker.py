import time

from app import ticker


def test_news_line_keeps_the_newest_and_shows_german(tmp_path):
    p = str(tmp_path / "t.json")
    now = time.mktime((2026, 11, 15, 12, 0, 0, 0, 0, -1))
    ticker.add("Leyla: Nachricht von Mama", "Ekmek al lütfen\n(Bitte Brot mitbringen)", p, now - 60)
    ticker.add("Leyla erzählt", "Umut war frech zu mir.", p, now - 30)
    ticker.add("Leyla", "alt", p, now - 4 * 24 * 3600)
    lines = ticker.recent(p, now)
    assert lines == [lines[0]] and lines[0].endswith("Leyla: Umut war frech zu mir.")  # only the newest
    ticker.add("Leyla: Nachricht von Mama", "Ekmek al lütfen\n(Bitte Brot mitbringen)", p, now)
    newest = ticker.recent(p, now)
    assert len(newest) == 1 and newest[0].endswith("Mama: Bitte Brot mitbringen")
    assert newest[0].startswith("12:00")
    for i in range(30):
        ticker.add("Leyla", f"n{i}", p, now)
    assert len(ticker._load(p)) == ticker.KEEP and len(ticker.recent(p, now)) == ticker.SHOW_ITEMS


def test_who_and_plain():
    assert ticker.who("Leyla: Nachricht von Umut") == "Umut"
    assert ticker.who("Leyla meldet") == "Leyla"
    assert ticker.plain("a\n b ") == "a b" and ticker.plain("x" * 300).endswith("…")
