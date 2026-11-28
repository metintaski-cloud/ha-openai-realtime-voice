"""Open points of her memory (app/punkte.py). Invented, neutral sentences only."""
from app import punkte


def test_points_wait_until_decided_and_are_not_asked_twice(tmp_path):
    p = punkte.Points(str(tmp_path / "p.json"))
    assert p.add([{"art": "neu", "liste": "family", "neu": "Person: Ali | Zugehörigkeit: Metins Neffe"},
                  {"art": "widerspruch", "liste": "family", "alt": "Geburtstag: 01.02.", "neu": "Geburtstag: 03.02.",
                   "name": "Ali", "feld": "Geburtstag"},
                  {"art": "quatsch", "neu": "x"}, "kein Punkt"]) == 2
    assert p.add([{"art": "neu", "liste": "family", "neu": "person: ali |  zugehörigkeit: metins neffe"}]) == 0
    opened = p.open()
    assert [x["art"] for x in opened] == ["widerspruch", "neu"]          # decisions first
    assert p.counts() == {"neu": 1, "widerspruch": 1, "mensch": 0, "unklar": 0, "abgelaufen": 0}
    assert p.done(opened[0]["id"], "alt bleibt") and not p.done(opened[0]["id"])
    assert [x["art"] for x in p.open()] == ["neu"]
    assert p.add([{"art": "widerspruch", "liste": "family", "alt": "Geburtstag: 01.02.", "neu": "Geburtstag: 03.02.",
                   "name": "Ali", "feld": "Geburtstag"}]) == 0           # decided: not asked again these days
    assert p.get(opened[0]["id"])["entscheidung"] == "alt bleibt"


def test_private_points_show_only_behind_the_code_word(tmp_path):
    p = punkte.Points(str(tmp_path / "p.json"))
    p.add([{"art": "neu", "liste": "private", "neu": "etwas nur für ihn", "privat": True},
           {"art": "mensch", "name": "Ali"}])
    assert [x["art"] for x in p.open(private=False)] == ["mensch"]
    assert len(p.open(private=True)) == 2
