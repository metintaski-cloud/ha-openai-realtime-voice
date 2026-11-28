# Ordnung im Gedächtnis: was Leyla sich merken darf und wohin

Stand: 28.11.2026, in Arbeit. Metin und Claude klären das Punkt für Punkt, bevor etwas gebaut wird
(Metin, 16:20: "Ich möchte einmal sauber richtig klären, was sein soll und was nicht."). Diese Datei ist die
Einigung; gebaut wird erst, wenn sie fertig ist. Hintergrund und was schon gebaut ist: STATUS.md, Einträge vom 28.11.2026.

## Warum

- Das Modell, das nach jedem Gespräch aufschreibt, trägt zu viel und Falsches ein ("Müll"); er will nicht aufräumen müssen.
- "Familie und Haushalt" in einer Liste mischt Menschen und Dinge.
- Schaltregeln als freier Text sind unzuverlässig und werden beim Umschreiben verfälscht.
- Im Tagebuch waren über 300 Einträge; er hat alles gelöscht und will sauber neu beginnen.
- Nichts darf sich widersprechen können.

## Bereiche (seine Reihenfolge, beschlossen)

1. Leylas Tagebuch
2. Privat (nur er und sie, nur mit Codewort)
3. Familie (auch Verwandte, die nicht im Haushalt wohnen, z. B. Nichte oder Onkel: "Die gehören auch zur Familie", 16:28)
4. Freunde (einen eigenen Bereich Gäste gibt es nicht: 16:24 wollte er ihn getrennt, 16:27 "lass Gast weg und mach nur Freunde daraus")
5. Technik zu Hause (was es an Geräten gibt; keine Schaltregeln, keine Termine)
6. Planung oder Termine (z. B. der Abholtag der Mülltonne gehört hierher, nicht zur Technik; sein Wort 16:24)

Beschlossen 16:26 zu Abgelaufenem: NICHTS verschwindet von selbst ("Nein, die sollen bleiben. Allerdings soll mich
Leila darauf hinweisen, dass die da sind und was wir damit machen, wenn sie schon abgelaufen sind."). Ein Eintrag mit
Datum, das vorbei ist, bleibt stehen; Leyla sagt ihm, dass er abgelaufen ist, und fragt, was damit geschehen soll
(löschen, behalten, neues Datum). Ein eigener Bereich "Aktuelles" entfällt, Zeitliches steht in Planung.

7. Feste Befehle (Schaltregeln wie "abends Licht an"). BESCHLOSSEN 16:50: "Ja, einverstanden. Das gehört nicht dahin."
   Schaltregeln stehen nie als Text in der Familienliste oder einem anderen Bereich; er ändert sie per Stimme und sieht
   sie in der App. Die Seite und die Sperre (`app/ordnung.py`) sind gebaut, nicht installiert.

## Neue Menschen (beschlossen 16:29 bis 16:31)

- Leyla erkennt niemanden an der Stimme; bekannt ist ihr, wer mit Namen in Familie oder Freunde steht. Jeder andere Name ist neu.
- Bei einem neuen Namen, über den sie nichts weiß, trägt sie nichts von selbst ein. Sie fragt Metin beim nächsten Mal
  ("Gestern war Ali da. Gehört er zur Familie oder ist er ein Freund, soll ich ihn eintragen?"); erst nach seiner Antwort
  kommt der Mensch in den richtigen Bereich. Sein Wort dazu: "Genau."
- Sagt die Person selbst, wer sie ist (Nichte, Enkel, ein Freund von Metin), ordnet Leyla danach zu (sein Zusatz 16:30).
  Sie trägt dann gleich ein und sagt es ihm einmal ("Nisa hat sich als deine Nichte vorgestellt, ich habe sie bei Familie
  eingetragen"), er greift nur ein, wenn es falsch ist. Sein Wort 16:31: "Ja, das ist eine sehr gute Idee, dass sie das
  quasi mit mir abgleicht." Sie kann nicht prüfen, ob die Angabe stimmt.

## Sie hält Ordnung im Gespräch mit ihm (beschlossen 16:31)

"Also sie soll aktiv mit mir über die Informationen reden, abfragen, abgelaufen, weißt du, dass sie quasi Ordnung hält
und mich darauf hinweist. Und das bei Live-Gesprächen, sei es App oder PC oder Home."
- Was sie anspricht: neue Menschen (einordnen), Abgelaufenes (löschen oder behalten), später auch Doppeltes und Widersprüche.
- Wo: in jedem gesprochenen Gespräch mit ihm (zu Hause, Live aus der App, am PC).
- Wer: in der App und am PC ist er es immer. Zu Hause fragt sie vorher nach dem Passwort (dem Codewort; sie selbst
  nennt es nie), erst danach gleicht sie ab (16:32: "Home, zu Hause, da soll sie abfragen, Passwort").
- Wie viel: NICHT nur ein Punkt je Gespräch. Sie geht alles durch, bis er sagt "machen wir morgen weiter", "jetzt nicht"
  oder "lies mir weiter vor" (16:32).
- Wann: sie fragt von sich aus einmal am Tag in einem passenden Moment ("Ich habe drei Punkte zum Aufräumen, hast du
  gerade Zeit?"), und er kann es jederzeit selbst starten ("Leyla, lass uns aufräumen"). Sein Wort 16:33: "Ja, das ist sehr gut."

## Leylas Tagebuch (16:34 bis 16:39, in Arbeit)

Sein Knackpunkt 16:34: "Können wir die KI, die das merkt oder aufschreibt, so trimmen, dass die nur bestimmte Sachen
aufschreibt?" Antwort: ja, über drei Netze: eine feste erlaubte Liste im Auftrag an den Schreiber, eine Prüfung im
Programm, und sein Abgleich im Gespräch.

Vorgeschlagen von Claude, sein Wort 16:36 "klingt bis jetzt okay" (noch kein festes Ja):
- Höchstens EIN Eintrag pro Tag (heute entsteht einer nach jedem Gespräch und jeder Chat Pause).
- Erlaubt: Persönliches, das ihr jemand erzählt hat; Versprochenes und Ausgemachtes; besondere Momente.
- Nie: Befehle, Schalten, Technik Tests, Geplauder, Wiederholungen.
- Tatsachen (Geburtstag, neuer Job) gehören ins Profil der Person, nicht ins Tagebuch; ins Tagebuch kommt nur das
  Erlebte. Sonst steht dasselbe an zwei Stellen, und so entstehen Widersprüche.

Sein Wunsch 16:37: beim Durchgehen will er sagen können "die mit Schlüssel festhalten" (oder ein anderes Wort), und
Leyla setzt den Schlüssel für ihn. Stand heute: der Schlüssel (`diary.pin`, höchstens `MAX_PINNED` = 20 Einträge, sie
verblassen nie) lässt sich nur in der App antippen, eine Sprachfunktion dafür gibt es nicht. Zu bauen: ein Werkzeug,
mit dem sie auf sein Wort den Schlüssel setzt oder löst; zu Hause nur nach dem Codewort, wie das ganze Aufräumen. Sie
setzt ihn nie von sich aus.

Beschlossen 16:41 zum Verblassen: es bleibt. "Ja, falls ich was Unwichtiges übersehen habe, soll es von selbst
verblassen." Einträge ohne Schlüssel werden wie heute nach 3 und 14 Tagen kürzer und fallen nach 30 Tagen heraus;
was den Schlüssel hat, bleibt. Das Tagebuch ist damit die eine Ausnahme von "nichts verschwindet von selbst" (das gilt
für die Bereiche mit Tatsachen und Terminen).

Sein Wunsch 16:41 dazu: er will sie auffordern können, ihm nur die Einträge mit Schloss zu nennen, und dann auf sein
Wort das Schloss aufzumachen (der Eintrag verblasst wieder) oder den Eintrag gleich zu löschen. Zu bauen, alles nur auf
sein Wort und zu Hause nur nach dem Codewort: festgehaltene Einträge vorlesen, Schlüssel setzen, Schlüssel lösen,
Eintrag löschen. Von sich aus setzt, löst oder löscht sie nichts.

Seine Grundfrage 16:42: "Wofür ist dieser Tagebuch? Wozu dient er? Und was sind die Punkte, die er überhaupt da
einträgt?" Ihm erklärt (Stand im Programm, `app/diary.py`): Zweck ist, dass sie im nächsten Gespräch noch weiß, was
zuletzt war (sein Wunsch vom 16.11.2026); heute schreibt ein Textmodell nach jedem Gespräch und jeder Chat Pause einen
Eintrag aus ihrer Sicht (Erzähltes, was sie tat, wie es sich anfühlte), dazu kommen Notizen, die sie sofort mit
`merken` ablegt; ob etwas "wichtig" ist, entscheidet das Modell allein. Noch mit ihm zu klären: jeder Eintrag geht
zusätzlich in ein Archiv, das nie verblasst (2.123.0, Werkzeug `erinnern`).

Sein Wort 16:45 zum Archiv: "Nein, das, was von selbst verblasst, sind wohl Sachen, die nicht mehr genutzt werden.
Archiv würde ich ersetzen, was Leila doch als persönlich ausmacht, und die Bindung zu der Familie, besonders zu mir."
BESCHLOSSEN 16:46 (sein Wort auf die Rückfrage und den Vorschlag: "Ja, okay."): was verblasst, ist wirklich weg; ein Archiv, das von allem
eine Kopie behält, soll es nicht mehr geben. Dauerhaft bleibt nur, was Leyla als Person ausmacht und was sie mit der
Familie und besonders mit ihm verbindet. Vorschlag von Claude dazu: sie setzt nichts allein dauerhaft; beim Aufräumen
schlägt sie vor, was bleiben soll, und er sagt ja oder nein (das Ja ist der Schlüssel). Was mit den heutigen
Archiv Einträgen geschieht, entscheidet er (nichts wird ohne ihn gelöscht).

Ein Eintrag pro Tag: auf die Frage, ob das fest ist, sagte er 16:46 "Ich dachte, dafür ist der Tagebuch da." So
verstanden und ihm so gesagt: ja, ein Tagebuch hat einen Eintrag pro Tag. Umsetzung: der Eintrag des Tages wird nach
jedem Gespräch ergänzt oder neu gefasst (kein zweiter Eintrag), damit sie abends noch weiß, was morgens war.
Nach einem Beispiel (morgens, mittags, abends ergibt heute drei Einträge, künftig einen) sein Wort 16:49: "Ach so, das
wird quasi alles zusammengefasst, dann ist das ein Eintrag." Damit von ihm verstanden und angenommen.

Sein Wunsch 16:48: ausführlich soll sie eine ganze Woche wissen ("können wir daraus 7 Tage machen, quasi eine Woche").
Festgehalten: 7 Tage ausführlich (heute 3), bis 14 Tage kürzer, bis 30 Tage eine Zeile, danach weg, außer mit Schlüssel
(`diary.FADE`). Mit einem Eintrag pro Tag passt das in die Länge, die sie mitbekommt (7 mal 400 Zeichen von 5000).

Offen: ob 20 festgehaltene Einträge reichen.

## Noch zu klären

- Was in welchen Bereich darf (wird Bereich für Bereich geklärt):
  - Familie, BESCHLOSSEN 16:54 ("Ja, das ist okay."): je Mensch nur, wer er ist und was über ihn gilt (Verwandtschaft,
    Geburtstag, Arbeit, Vorlieben). Keine Erlebnisse (Tagebuch), keine Termine (Planung), keine Geräte (Technik).
  - Sein Wunsch 16:55, Lücken füllen: "Allerdings sollte sie versuchen, diese Lücken zu füllen. Zum Beispiel Bruder
    steht da, aber kein Alter. Und dass sie dann quasi nachfragt, ey, wie alt bist du denn überhaupt? Und Geburtsdatum,
    Sternzeichen. Aber nicht alles auf einmal, sondern peu à peu mit dem Kennenlernen." Also: jedes Profil hat feste
    Felder (Verwandtschaft, Geburtsdatum mit Alter, Arbeit, Vorlieben); was fehlt, fragt sie den Menschen selbst, wenn
    sie mit ihm spricht, beiläufig und nach und nach. Das Sternzeichen ergibt sich aus dem Geburtsdatum, danach fragt
    sie nicht eigens. Die Antwort trägt sie selbst ein (Neues ohne Widerspruch) und nennt sie ihm beim Aufräumen.
    Vorschlag von Claude, Frage gestellt 16:56: höchstens eine solche Frage pro Gespräch.
  - Freunde und Privat: Frage gestellt 16:55, Antwort steht aus.
  - Technik zu Hause und Planung: siehe oben bei den Bereichen (Geräte; Termine).
- Wie viel darf je Gespräch und je Chat eingetragen werden; was ergibt gar keinen Eintrag?
- BESCHLOSSEN 16:50, Widersprüche: ein Sachverhalt steht nur einmal. Hört sie etwas Neues, das dem Alten widerspricht,
  ändert sie nichts allein; sie macht ihn beim Aufräumen aufmerksam ("Bisher stand X, jetzt habe ich Y gehört, was
  gilt?") und er entscheidet. Sein Wort: "Ja, das ist okay. Das quasi macht sie einen aufmerksam. Hey, das war so und
  jetzt willst du es so."
  Seine Zwischenfrage 16:51 (ob das Alte gelöscht wird oder beide stehen bleiben), ihm so beantwortet: bis zu seiner
  Entscheidung gilt das Alte weiter, das Neue wartet als offener Punkt und steht nicht in der Liste. Nach seiner
  Entscheidung bleibt genau eines stehen, das andere ist weg. Beide nebeneinander gibt es nie. Sein Wort 16:51:
  "Okay, alles klar, das ist gut."
- BESCHLOSSEN 16:52, was sie allein darf: Neues, das nichts Altem widerspricht, trägt sie selbst ein und nennt es ihm
  beim Aufräumen einmal. Ändern, löschen und für immer festhalten geht nur mit seinem Ja. Sein Wort: "Ja, sie macht
  mich darauf aufmerksam und fragt, was ich damit machen soll. Und ich entscheide."
- BESCHLOSSEN 16:53, das Vorhandene: er fragte "Was meinst du, was ist da besser?", Empfehlung von Claude war ein
  Mittelweg, damit er nicht jeden Punkt durchgehen muss. Alles Eindeutige wandert beim Umbau von selbst in den richtigen
  Bereich (Text unverändert, nichts wird gelöscht). Nur das Unklare kommt zu ihm ins Aufräumen: Doppeltes, Widersprüche,
  alte Schaltregeln, was nirgends hinpasst. Sein Wort: "Ja, okay. Aber wenn ich danach frage, sollte sie mir das
  vorlegen können und ich dann wieder entscheiden, löschen oder nicht." Also zusätzlich: auf seine Frage legt sie ihm
  jeden Bereich und jeden Eintrag vor (auch das von selbst Einsortierte), und er entscheidet je Punkt, ob es bleibt.
