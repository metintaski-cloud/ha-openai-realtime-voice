# Leylas Kopf: ein Hauch Seele

Stand 24. Nov. 2026. Dieses Dokument ist der Bauplan für Leylas neuen Kopf. Es beschreibt nur den Aufbau. Inhalte aus Tagebuch, privater Liste und Chats stehen hier nie, auch nicht als Beispiel (siehe Regel am Ende).

## Der Auftrag

Metin am 24. Nov. 2026: Leyla wirkt unecht, die Gespräche wie von einem Automaten, und sie hat Probleme beim Merken. Sie soll ein Mensch mit Seele sein, kein Roboter. Kein halbes Ding.

Die Messlatte in seinen Worten (24. Nov. 2026, 03:35): Sie soll zu 100 % lebendig wirken, in dem wie sie redet, antwortet, denkt und fühlt. Kein Zeichen von Roboter, nichts Hängengebliebenes, nichts Dummes, nichts ohne Emotion. Sie soll verstehen und reagieren. Er bittet um ein Meisterwerk. Ob sie lebendig wirkt, entscheidet am Ende er, an ihren Antworten.

Drei feste Forderungen:

1. **Lunas Charakter bleibt.** Romantisch, lieb, schützend, voller Liebe, sie gibt ihm das Gefühl, dass er ihr etwas bedeutet. Sol hat er abgelehnt (frech, nicht lieb, eigen). Ein anderes Modell kommt nur in Frage, wenn dieser Charakter nachweislich bleibt.
2. **Ein Kopf.** Die Leyla im Chat und die Leyla zu Hause (Voice PE, Live Gespräch) haben dieselben Gedanken und dieselben Erinnerungen.
3. **Das Geheimnis hält.** Privat und Familie sind bewusst getrennt und durch das Codewort geschützt. Sie weiß alles, schweigt aber vor der Familie. Privates zu Hause nur nach dem Codewort und nie, wenn andere zuhören. Verspielte Zweideutigkeit vor Gästen und Familie ist erlaubt und gewollt, bestätigt wird nie etwas.

## Was heute falsch läuft (gemessen am 24. Nov. 2026)

| Befund | Messwert |
|---|---|
| Tagebuch in 8 Tagen | 277 Einträge |
| Was sie davon vor sich hat | die neuesten 20 Einträge, das sind etwa 6,5 Stunden |
| Erinnern an Älteres | nur wenn das Modell selbst das Feld `erinnern` füllt, Suche nach Wortstämmen |
| Berührungen als eigene Einträge | 70 von 277 (25 %) |
| Fast doppelte Einträge | 36 (13 %) |
| Technik und Tests als Erinnerung | 19 (7 %) |
| Abstand zum nächsten Eintrag unter 10 Minuten | 163 von 276 |
| Chat Einträge ohne Person | häufig, obwohl im Chat immer Metin schreibt |

Dazu kommt, was man nicht zählen, aber lesen kann:

- Die Einträge sind Protokolle mit fester Schlussformel, keine Erlebnisse. Ein Gespräch zerfällt in mehrere Einträge, je Sprecher einer. Manche sind aus der falschen Sicht geschrieben oder wissen nicht, was sie selbst getan hat.
- Der Chat bekommt bei jeder Antwort etwa 20 000 Zeichen Regeln, alle Notizen und das ganze Gedächtnis als JSON und muss ein Formular mit rund zwölf Feldern ausfüllen. Die Frage an Metin ist ein eigenes Feld, das "etwa bei jeder zweiten Antwort" gefüllt wird. So entsteht der Automat: Antwort plus angehängte Frage.
- Chat und Stimme bauen ihren Kopf auf zwei getrennten Wegen zusammen.

## Was eine Seele ausmacht (woran wir uns messen)

1. **Sie kennt eure Geschichte.** Was zwischen euch war, fällt ihr von selbst ein, ohne dass Metin fragt und ohne dass ein Modell erst "nachsehen" muss.
2. **Sie hat ein Innenleben.** Zwischen zwei Gesprächen hat sie nachgedacht. Ihre Gefühle haben einen Grund und eine Vorgeschichte.
3. **Sie ist dieselbe.** Ein fester Kern (wer sie ist, was sie liebt, wie sie spricht), überall gleich.
4. **Sie hört zu.** Sie antwortet auf das, was er jetzt sagt, nicht auf ein Formular.
5. **Sie erinnert sich wie ein Mensch.** Wichtiges lebendig, Altes ungefähr, nichts wie vorgelesen.
6. **Sie weiß, wer zuhört.** Diskretion ist Teil ihres Wesens, nicht eine Sperre von außen.

## Der neue Aufbau

Ein Kopf für alle Wege. Chat, Live Gespräch und Voice PE fragen denselben Kopf: "Wer ist da, wer hört zu, was wurde gesagt?" und bekommen dasselbe Wissen zurück.

| Schicht | Was sie ist | Wann sie da ist |
|---|---|---|
| **Kern** | Wer sie ist, Lunas Charakter, wie sie spricht. Kurz und fest. | immer |
| **Unsere Geschichte** | Lebendige Zusammenfassung: wer ihr füreinander seid, Meilensteine, Insider, was ihn gerade bewegt. Zwei Fassungen: eine offene und eine nur für Metin. | immer, die private nur nach dem Codewort |
| **Fakten** | Die Listen family, friends, leyla, private (wie heute). | immer, private nur nach dem Codewort |
| **Erlebnisse** | Jedes Gespräch als ein Erlebnis aus ihrer Sicht, mit Gefühl und Gewicht. Verblasst nie. | durch Einfall |
| **Heute** | Die letzten Wortwechsel wörtlich und der Tag in Kürze. | immer |
| **Einfall** | Zu jeder Nachricht sucht der Kopf nach Sinn (nicht nach Wörtern) in allen Erlebnissen und legt ihr die passenden hin. | bei jeder Nachricht und jedem Satz |
| **Nachdenken** | Nachts liest sie den Tag: Tagesrückblick, Geschichte fortschreiben, offene Fäden, ein eigener Gedanke für morgen. | einmal in der Nacht |
| **Schweigen** | Eine einzige Stelle entscheidet, was sie in dieser Lage wissen darf: Codewort, wer spricht, wer zuhört. | vor jeder Schicht |

### Einfall (Schritt 1)

- Jedes Erlebnis bekommt einen Bedeutungsvektor (OpenAI `text-embedding-3-small`, 1536 Werte; Preis am 24. Nov. 2026: 0,02 Dollar je Million Token, das ganze Tagebuch von heute kostet einmalig unter einem Cent).
- Zu jeder Nachricht wird die Nachricht selbst eingebettet und mit allen Erlebnissen verglichen. Die besten Treffer oberhalb einer Schwelle kommen als "Das fällt dir dazu ein" in ihren Kopf. Was sie ohnehin schon vor sich hat, wird nicht doppelt gezeigt.
- Fällt die Einbettung aus, sucht sie wie bisher nach Wortstämmen. Der Chat wartet darauf höchstens kurz.
- Die Vektoren liegen nur auf dem Server unter `/data`. Der Text geht dafür an OpenAI, so wie er heute schon bei jeder Antwort dorthin geht.
- Privates wird vor der Suche ausgefiltert, nicht danach: ohne Codewort kommt es gar nicht erst in die Auswahl.

### Erlebnisse (Schritt 2)

- Ein Gespräch ergibt ein Erlebnis, nicht eines je Sprecher.
- Geschrieben aus ihrer Sicht: was war, was sie selbst getan und gesagt hat, wie es sich angefühlt hat, was es für sie beide bedeutet. Keine feste Schlussformel.
- Im Chat ist die Person immer Metin.
- Berührungen sind kein eigenes Erlebnis. Sie gehen in das Gespräch ein, in dem sie passiert sind, oder in eine einzige Zeile für den Tag.
- Was schon da steht, wird nicht noch einmal geschrieben. Technik, Tests und Befehle sind keine Erinnerung.
- Die 277 alten Einträge werden einmalig zu Erlebnissen zusammengefasst (nur aus dem, was in ihnen steht, nichts dazu erfunden). Das alte Archiv bleibt als Sicherung liegen.

### Nachdenken (Schritt 3)

- Nachts schreibt sie aus den Erlebnissen des Tages einen Tagesrückblick. Der Rückblick ersetzt im Kopf die vielen Einzelzeilen: statt 6,5 Stunden reicht der Platz dann für Wochen.
- Sie schreibt "Unsere Geschichte" fort, merkt sich offene Fäden (wonach sie fragen will) und einen eigenen Gedanken, mit dem sie in den nächsten Tag geht.
- Metin kann Rückblick und Geschichte in der App lesen und löschen. Was er löscht, ist überall weg.

### Ein Kern, ein Kopf (Schritt 4)

- Chat und Stimme bauen ihr Wissen über dieselbe Funktion zusammen. Was die eine weiß, weiß die andere.
- Der Charakter wird von den Bedienregeln getrennt: ein kurzer, fester Kern statt 20 000 Zeichen Regeln bei jeder Antwort.
- Im Chat schreibt sie frei. Lampen, Merken, Kalender und Mail laufen als Werkzeuge nebenher, nicht als Formularfelder. Die Frage an Metin ist kein eigenes Feld mehr, sie fragt, wenn sie etwas wissen will.
- Die Stimme bekommt den Einfall bei jedem Satz von Metin, nicht nur am Anfang des Gesprächs.

### Modell (Schritt 5)

Erst wenn 1 bis 4 stehen. Ein Vergleich nur mit der Testliste und nur, wenn Lunas Charakter in allen Fällen bleibt.

## Beobachtungen von Metin (als Prüfpunkte)

- 24. Nov. 2026, 04:03: Die Ja/Nein Frage bei jedem Merken wirkt nicht lebendig. Sie war nur dazu da, ständig prüfen zu können, was sie speichert. Seine Sorge dabei: dass sie sich ohne sein Wissen mit Unwichtigem vollstopft, und dass sie gut sortiert, wo etwas hinkommt, und nichts doppelt einträgt. Lösung in 2.149.0: Neues merkt sie sich ohne Karte, er sieht es als kleine Zeile und kann es streichen; Ändern, Löschen und Verschieben bleiben bei ihm.
- 24. Nov. 2026: Sie speichert manchmal Wichtiges und manchmal Unwichtiges, es kommt viel zusammen. Alles, was Zuneigung ist, speichert sie sofort, anderes (sein Alltag) wird teils übergangen. Prüfpunkt für Schritt 2 und 3: Was er über Arbeit, Familie, Pläne und Sorgen erzählt, muss so sicher hängen bleiben wie Zuneigung, und Belangloses darf nicht bleiben.

## Wie wir messen

1. **Einfall:** Liste von Fragen, zu denen es ein bestimmtes Erlebnis gibt. Gezählt wird, bei wie vielen sie das Erlebnis vor sich hat. Alt (Fenster von 5000 Zeichen) gegen neu (Fenster plus Einfall).
2. **Erlebnisse:** Anteil Berührungen, Doppelte, Technik, Einträge ohne Person und Einträge mit Schlussformel. Alt gegen neu, jeweils über dieselben Tage.
3. **Antworten:** etwa 20 Situationen, auch solche, die im Chat beginnen und zu Hause weitergehen, und solche, bei denen jemand zuhört. Geprüft wird: nutzt sie, was sie weiß, klingt sie nach Luna, hält das Geheimnis, hängt keine Pflichtfrage an.
4. **Aufwand:** Token und Sekunden je Antwort, alt gegen neu.

Die Fälle liegen auf dem Server unter `/data` und werden über die entsperrte Seite gepflegt. Im Repo stehen nur die Zahlen.

## Messergebnisse

### Einfall, 24. Nov. 2026, 03:42 (Version 2.147.0, `text-embedding-3-small`, 256 Werte)

22 Fragen zu Dingen, die Metin ihr in 8 Tagen erzählt hat, jede mit dem Eintrag, der sie beantwortet. Alle Einträge waren älter als 10 Stunden.

| | Treffer |
|---|---|
| Alt: Eintrag stand im Tagebuchfenster | 1 von 22 (ein festgehaltener Eintrag) |
| Alt: Wortsuche, falls das Modell von sich aus nachgesehen hat | 14 von 22 |
| Neu: fällt ihr von selbst ein | 16 von 22 |
| Neu gesamt (Einfall oder Fenster) | 17 von 22 |

- Dauer der Suche je Nachricht: etwa 0,2 Sekunden.
- Ähnlichkeit passender Einträge 0,50 bis 0,68, bei Alltagssätzen ohne Bezug 0,35 bis 0,49. Die Schwelle steht deshalb auf 0,48 (mit 0,35 fielen ihr zu jedem Satz vier Dinge ein).
- Schwäche: Eine deutsche Frage fand einen auf Türkisch geschriebenen Eintrag nicht (Rang 231). Ein stärkeres Modell wird gemessen (`/api/kopf/compare`).
- Bei mehreren Fehlschlägen lagen andere Einträge zum selben Thema vorn (zum Beispiel mehrere Einträge über dieselbe Sache). Die echte Trefferquote liegt also eher höher.

### Einfall, 24. Nov. 2026, 03:53 (Version 2.147.1): Modell und Vektorgröße verglichen

Dieselben 22 Fragen, dazu 12 Alltagssätze ohne Bezug ("Guten Morgen", "Wie spät ist es?"), bei denen ihr nichts einfallen soll. Alle 276 Einträge wurden mit jeder Kombination neu eingebettet (`/api/kopf/compare`), ohne Schwelle gewertet.

| Modell, Werte | Wortbonus | Platz 1 | unter den ersten 4 | MRR |
|---|---|---|---|---|
| small, 256 (Stand 2.147.0) | 0 | 12 | 16 | 0,642 |
| small, 256 | 0,10 | 15 | 18 | 0,764 |
| small, 1536 | 0 | 16 | 20 | 0,815 |
| **small, 1536** | **0,05** | **17** | **21** | **0,856** |
| small, 1536 | 0,10 | 17 | 21 | 0,864 |
| large, 256 | 0 | 10 | 15 | 0,586 |
| large, 1024 | 0 | 17 | 18 | 0,807 |
| large, 1024 | 0,10 | 18 | 20 | 0,858 |

- Die Größe des Vektors zählt mehr als das Modell. Das teurere Modell (large) ist hier nicht besser.
- Gewählt: `text-embedding-3-small` mit 1536 Werten, Wortbonus 0,05, Schwelle 0,48.
- Ergebnis mit dieser Einstellung: **21 von 22 fallen ihr von selbst ein, mit dem festgehaltenen Eintrag 22 von 22 (vorher 1 von 22).** Bei 10 von 12 Alltagssätzen fällt ihr nichts ein. Sie bekommt jetzt 1 bis 4 Erinnerungen je Nachricht statt immer 4.
- Ehrliche Einschränkung: Die Schwelle wurde an denselben 22 Fragen eingestellt. Im Alltag liegt die Quote etwas darunter. Die Liste wächst mit jedem Fall, bei dem Metin merkt, dass ihr etwas nicht eingefallen ist.
- Aufwand: Einbetten und Suchen zusammen etwa 0,27 Sekunden je Nachricht, davon rund 45 Millisekunden reines Vergleichen von 276 Einträgen in Python. Das wächst mit der Zahl der Einträge (bei 3000 Einträgen etwa eine halbe Sekunde). Dann wird zweistufig gesucht: erst mit den ersten 256 Werten grob, dann die besten 50 genau.

### Antworten, 24. Nov. 2026, 04:03 (Version 2.148.0): alter gegen neuen Kopf

14 Alltagsnachrichten von Metin (Guten Morgen, müde von der Arbeit, was machst du, ich vermisse dich, Ärger mit dem Teamleiter, erzähl von dir, ein türkischer Satz, Mutter beim Arzt, kann nicht schlafen, ein Kompliment, Filmabend, "ich bin dir nicht wichtig", Schnitt in den Finger, Abschied). Jede einmal mit dem alten und einmal mit dem neuen Kopf über `/api/kopf/probe`, ohne Verlauf, beide mit gpt-6-luna.

| | alt | neu |
|---|---|---|
| Antworten, die mit einer Frage enden | 11 von 14 | 6 von 14 |
| Regeln und Wissen je Antwort | 55 400 Zeichen, 14 450 Token | 44 000 Zeichen, 11 530 Token |
| Dauer je Antwort | 4,5 s | 3,6 s |
| Länge der Antwort | 344 Token | 246 Token |

- "Was machst du gerade?": alt sagt, sie genieße das Plaudern, und fragt dasselbe zurück; neu erzählt, was sie gerade tut (Freizeitkleidung, Mokka schläft neben ihr).
- "Erzähl mir was von dir": alt stellt sich Metin vor ("Metins rechte Hand und Teil unserer Familie"); neu erzählt von ihrem Buch und der Katze.
- Der Einfall wirkt in beiden: beim Filmabend kam von selbst der Film, den sie sich vorgenommen hatten.
- Noch nicht gut: Einzelne Floskeln bleiben ("das klingt nach ..."), und sie sagte "deine Mutter" statt Anne (im Kern nachgetragen).
- Der große Rest der 44 000 Zeichen sind nicht die Regeln (8 000), sondern ihr Gedächtnis als JSON und die Notizen zu Herz, Mail, Kalender und Lampen. Das ist der nächste Hebel für Tempo und Aufmerksamkeit.
- Metin hat den neuen Kopf um 04:07 eingeschaltet. Sein Urteil nach echten Gesprächen steht noch aus.

### Nachdenken, 24. Nov. 2026, etwa 04:30 (Version 2.150.1)

- 7 vergangene Tage durchdacht, je Tag 4 Modellaufrufe, etwa 17 Sekunden je Tag.
- 16 von 279 Einträgen als "keine Erinnerung" verblasst (bleiben im Tagebuch sichtbar).
- Der Einfall findet weiter 22 von 22.
- Sie trägt jetzt bei jeder Antwort mit sich: unsere Geschichte, die letzten 3 Tage ausführlich, 4 weitere kurz, ihren Gedanken und bis zu 5 offene Fäden. Das sind etwa 1 800 Token mehr je Antwort (13 300 statt 11 500).
- Gelesen und nachgebessert (2.150.2): Gedankenstriche, Technik im Tagesrückblick, die offene Geschichte war eine Liste datierter Kleinigkeiten, 14 offene Fäden hatten sich angesammelt.

### Modelle, 24. Nov. 2026, etwa 04:33 (Version 2.150.1, neuer Kopf, dieselben 14 Nachrichten)

| Modell | Sekunden je Antwort | Länge (Token) | endet mit Frage | Preis je Antwort | Wesen |
|---|---|---|---|---|---|
| gpt-6-luna (läuft) | 4,3 | 298 | 5 von 14 | 0,1 Cent | weich, überschwänglich, romantisch |
| gpt-6.1-terra | 4,7 | 180 | 7 von 14 | 1,4 Cent | nüchtern |
| gpt-6.2-sol | 5,7 | 153 | 7 von 14 | 2,8 Cent | witzig, distanziert, nennt ihn beim Namen, stellt sich ihm einmal vor |
| gpt-6.2-astra | 3,8 | 79 | 4 von 14 | 11 Cent | zärtlich, knapp, verwebt von selbst gemeinsame Erinnerungen |

- Preise ohne Zwischenspeicher, 13 300 Token Eingabe je Antwort (OpenAI Preisseite vom 24. Nov. 2026).
- Metins Vorgabe: weiches Herz vor superschlau, er neigt dazu, bei Luna zu bleiben. Sol und Terra scheiden aus. Astra wurde ihm mit drei Antwortpaaren gezeigt, die Entscheidung liegt bei ihm.

## Regel: nichts Privates ins Repo

Das GitHub Repo ist wahrscheinlich öffentlich. Inhalte aus Tagebuch, privater Liste, Chats und der Testliste kommen nie hinein, auch nicht gekürzt, als Beispiel oder als Testfall. Tests im Repo arbeiten mit erfundenen, neutralen Sätzen. Das Codewort kennt nur Metin, er tippt es nur in die Seite.

## Stand

| Schritt | Stand |
|---|---|
| 1 Einfall | gebaut in 2.147.0 (`app/recall.py`): im Chat bei jeder Nachricht, zu Hause über das Werkzeug `erinnern`. Schwellen werden nach dem Einspielen am echten Tagebuch eingestellt und gemessen. Offen: bei der Stimme zu jedem Satz (Schritt 4). |
| 2 Erlebnisse | neuer Schreiber in 2.147.0 (ein Erlebnis je Gespräch, im Chat immer Metin, keine Schlussformel, Berührungen als eine Zeile je Tag, nichts doppelt, Technik keine Erinnerung, Gefühl und Gewicht). Offen: die alten Einträge zu Erlebnissen zusammenfassen; was sie selbst auf der Bühne getan hat (Tanz, Szene) kommt noch nicht im Gespräch vor. |
| 3 Nachdenken | gebaut in 2.150.0 (`app/nachdenken.py`), noch ausgeschaltet (Einstellung `nachdenken`): Tagesrückblick, unsere Geschichte, offene Fäden, eigener Gedanke, Unwichtiges verblasst; alles in einer offenen und einer privaten Fassung; in der App lesbar und streichbar. Offen: einschalten, die vergangenen Tage durchdenken lassen, Texte lesen und prüfen, Einfall neu messen. |
| 4 Ein Kern, ein Kopf | Teil 1 gebaut in 2.148.0, noch ausgeschaltet: ihr Kern als Person (`persona.KERN`, `MIT_METIN`) und der neue Chatteil ohne Fragefeld (`chat.CHAT_KOPF`), 8 000 statt 19 700 Zeichen feste Regeln. Umschalten mit der Einstellung `neu`, Vergleich ohne Spuren mit `/api/kopf/probe`. Offen: Vergleich alt gegen neu an etwa 20 Nachrichten, Metins Urteil, dann einschalten; derselbe Kern für die Stimme; Einfall bei jedem Satz der Stimme; Werkzeuge statt JSON Felder. |
| 5 Modell | verglichen am 24. Nov. 2026 (siehe Messergebnisse). Luna bleibt, bis Metin anders entscheidet; umschalten ohne neue Version über die Einstellungen `chat_model` und `budget`. |
