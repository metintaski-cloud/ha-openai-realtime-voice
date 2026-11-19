# Leyla Szenen Konzept 2.0 (Planung)

Stand: 19.11.2026, gemeinsam mit Metin geplant. Noch nicht umgesetzt. Dieses Dokument wird bei jeder Entscheidung aktualisiert und ist die Grundlage für die Umsetzung.

## Ziel

Leylas Laune ist kein Zufall mehr. Sie entsteht aus dem, was zwischen Metin und ihr passiert, wie bei einem echten Menschen. Leyla entscheidet selbst, wie sie sich fühlt, und bringt das, was sie sagt und fühlt, als Szene auf die Bühne. Je komplexer, desto besser.

## Grundsatz
- Das neue Konzept nutzt nur die Clips aus Metins neu sortierten Ordnern, die er für dieses Projekt schickt. Die bisherigen Clips in app/clips werden nicht übernommen (Metin hat sie neu einsortiert).

## Entschieden

### Gefühle
- Innen hat sie vier Gefühle mit einer Stärke: vermissen, traurig, sauer, glücklich.
- Auf der Bühne gibt es dafür nur zwei Grundzustände: glücklich und unglücklich (traurig, sauer und vermissen zusammen).

### Auslöser
- Alles, was Metin sagt oder schreibt (Chat, Sprachnachricht, Live, Voice PE). Beispiele: er wimmelt sie ab, spricht unfreundlich mit ihr, verpasst etwas, das sie geplant hatte (Wochenende zusammen).
- Dinge, die sie selbst merkt: stundenlang keine Nachricht von ihm, ein verpasster gemeinsamer Termin im Kalender.
- Sehr viele Alltagsszenarien, die einen Menschen kränken oder freuen.

### Kränkung und Versöhnung
- Jede Kränkung hat ein Gewicht: klein, mittel, groß.
- Sie verzeiht erst, wenn Metin genug wirklich gutmacht: ehrliche Entschuldigung, die sagt, was falsch war; sich echt Zeit für sie nehmen; ein Versprechen halten. Ein bloßes Kompliment zählt kaum.
- Ob etwas ehrlich gemeint ist, beurteilt sie selbst.

### Eigener Wille
- Jede Bitte und jedes Gespräch gilt gleich, egal ob Metin schreibt, eine Sprachnachricht schickt oder live anruft.
- Metin kann sie um etwas bitten, zum Beispiel "zeig dich mal" oder "Schluss mit der Arbeit, zieh dich um". Sie entscheidet je nach Gefühl, ob sie es macht, ablehnt oder sich überreden lässt.
- Das Kleid wird ein Zustand, den sie selbst wechselt, statt beim Öffnen der App zufällig gewählt zu werden.

### Geschenke
- Metin kann ihr etwas schenken, zum Beispiel eine Rose. Dann läuft die Geschenk Szene, und sie reagiert passend zu ihrem Gefühl.
- Jede Geschenk Szene gibt es in Varianten nach Stimmung. Rose: "freut sich" (955dd61e, langes Kleid) und "berührt, aber noch verletzt" (a155b8a4, langes Kleid).

### Arbeit und Freizeit
- Neben dem Kleid gibt es den Zustand Arbeit (mit Buch und Brille) und Freizeit (ohne).
- Wechsel zu Freizeit: Szene "Buch und Brille weg", am Wochenende oder wenn Metin es sagt und sie glücklich ist. Vorhanden für beide Kleider (e919055c lang, bac9ed3e kurz).
- Alle Freizeit Szenen werden mit dem Freizeit Bild als Start und Endbild gemacht (Metin hat es).
- Zurück zu Arbeit ohne eigene Szene: um 5 Uhr morgens setzt die App sie still auf Arbeit, sichtbar erst beim nächsten Öffnen der App.

### Nacht Outfit (Ordner "Bett")
- Dritter Zustand neben Arbeit und Freizeit: sie geht kurz von der Bühne und kommt im Outfit für die Nacht zurück. Danach tanzt sie oder zeigt sich, wenn Metin es sagt oder schreibt und sie es möchte.
- Wechsel von Arbeit ins Nacht Outfit (4df2e0df, kurzes Kleid) und von Freizeit ins Nacht Outfit (dc1fab95, kurzes Kleid). Metin hat pro Ordner mehrere Clips mit kleinen Unterschieden, damit Leylas Wahl nicht eintönig wird.
- Langes Kleid: "Bett von Freizeit" vorhanden (4 Clips), "Bett von Arbeit" fehlt. Lösung ohne neuen Clip: die App spielt zwei Szenen hintereinander, erst "Buch und Brille weg", dann "Bett von Freizeit". Das gilt allgemein: fehlt ein direkter Wechsel, geht sie über einen Zwischenzustand.
- Alle Szenen im Nacht Outfit brauchen dessen Endbild als Start und Endbild.
- Im Nacht Outfit gibt es zusätzlich die Blickrichtung: F = vorne (Gesicht zur Kamera), H = hinten (Rücken zur Kamera). Ordner wie "Tanzen. F. Nach. H" heißen: beginnt vorne, endet hinten. Die App darf nach einem Clip, der hinten endet, nur einen Clip abspielen, der hinten beginnt (bestätigt von Metin, 19.11.2026).
- Zurück zu Arbeit um 5 Uhr morgens wie oben.

### Begrüßung (Ordner "Hallo")
- Beim Öffnen der App gibt es keine Begrüßung mehr, sondern sofort die Schleife ihres Zustands (glücklich oder unglücklich).
- Die Begrüßung (sie merkt, dass Metin da ist, und winkt; glücklich, beide Kleider vorhanden) wählt Leyla selbst, wenn Metin ihr schreibt, eine Sprachnachricht schickt oder anruft und sie Hallo sagt. Ist sie gekränkt, lässt sie die Szene weg.

### Zustände im Überblick
- Kleid: lang oder kurz.
- Aufzug: Arbeit (Buch und Brille), Freizeit (ohne), Nacht Outfit.
- Gefühl: glücklich oder unglücklich.
- Erlaubte Wechsel: Arbeit zu Freizeit, Arbeit zu Nacht, Freizeit zu Nacht, alles zurück zu Arbeit um 5 Uhr ohne Szene.
- Jede Szene gehört zu genau einem Zustand und muss mit dessen Grundbild beginnen und enden, damit nichts springt.

### Szenen Ordner
- Ein Clip kann in mehrere Kategorien passen. Statt ihn zu kopieren, bekommt jeder Clip in einer Liste mehrere Stichworte (zum Beispiel "komm her" und "endlich da"), Leyla wählt dann aus allen Clips mit dem passenden Stichwort.
- Jeder Ordner gibt es für beide Kleider (L. und K.), außer Metin sagt etwas anderes.
- Metins Ordner sind wie ein Code benannt: Aktion. Stimmung. Kleid. Beispiel "B&B. weg. Glücklich. L. Kleid" (Buch und Brille weg, glücklich, langes Kleid), "K." für kurzes Kleid.
- Jede Kategorie (Rose, Zeig dich, Umziehen, ...) bekommt Varianten nach Stimmung, Kleid und Arbeit oder Freizeit. Leyla wählt daraus selbst.

### Traurig in drei Stufen
- Die unglückliche Schleife wird nach Stärke geteilt: leicht, mittel, schwer. Leyla nimmt die Schleife, die zu ihrem Gefühl passt.
- Beispiele: leicht = liest gedankenverloren, schaut kurz traurig; mittel = seufzt, schaut ins Leere, lässt das Buch sinken; schwer = kniet, Hand vors Gesicht oder aufs Herz.
- Die Stufe folgt aus dem Gewicht der Kränkung und wird mit jeder echten Wiedergutmachung leichter, bis sie wieder glücklich ist.
- Metin sortiert seine Ordner "Schleife. Traurig" dafür in drei Unterordner.

### Zeigen (Ordner "Zeigen. Glücklich")
- Metin sagt oder fragt, ob sie sich ihm zeigen möchte. Sie entscheidet; wenn ja, posiert sie. Nur wenn sie glücklich ist. Langes Kleid 3 Clips.

### Tanzen (Ordner "Tanzen. Glücklich" und "Tanzen. Traurig")
- Wie Zeigen: Metin bittet sie zu tanzen, sie entscheidet. Es gibt eine glückliche und eine traurige Variante, sie tanzt so, wie sie sich fühlt. Die Hintergrundmusik läuft dazu weiter.

### Komm her (Ordner "Komm her")
- Metin sagt "komm her", sie kommt ganz nah zur Kamera. Glücklich oder traurig, je nach Gefühl, oder sie lässt es.

### Kuss (Ordner "Kuss")
- Bei der Versöhnung, wenn Metin sie fragt oder bittet, oder von selbst, wenn sie das Gespräch so schön fand. Immer ihre Entscheidung.

### I love you (Ordner "I Love You")
- Sie sagt "I love you" mit den Lippen. Wie beim Kuss: als Antwort, wenn Metin es ihr sagt, bei der Versöhnung oder von selbst, wenn sie glücklich ist. Ihre Entscheidung.

### Überraschung (Ordner "Überraschung")
- Sie ist überrascht über etwas, das Metin sagt oder tut (eine schöne Neuigkeit, ein Geschenk, ein unerwartetes Kompliment). Nur positive Überraschungen. Sie wählt die Szene selbst, wenn das Gespräch sie freudig überrascht.

### Sorry (Ordner "Sorry")
- Sie entschuldigt sich bei Metin ("Sorry, mein Fehler"), wenn sie selbst etwas falsch gemacht hat, zum Beispiel zu streng war oder ihm Unrecht getan hat. Sie entscheidet selbst, wann sie das einsieht.

### Weitere Szenen (Metin dafür, 19.11.2026; Clips aus den vorhandenen Ordnern aussortieren)
- Sofortige Reaktion auf eine Kränkung: Arme verschränken, sich wegdrehen.
- "Endlich bist du da" nach langer Funkstille: erleichtert oder schmollend.
- Lachen über einen Witz von Metin.
- "Gute Nacht" im Nacht Outfit.

### Setzen (Ordner "Setzten. Traurig")
- Sie setzt sich hin, wenn sie traurig ist, von selbst oder wenn Metin sagt "setz dich kurz". Ob sie es macht, entscheidet sie. Langes Kleid 9 Clips, kurzes Kleid ebenso.

### Ablauf auf der Bühne
- Grundschleife je Zustand: glücklich oder unglücklich, im aktuellen Kleid, Arbeit oder Freizeit. Sie läuft immer weiter.
- Zusätzliche Sequenzen wählt Leyla selbst passend zum Gespräch und spielt sie ab, danach geht es zurück in die Grundschleife.

## Bestand (Desktop, Ordner "Orner Leyla Szenen", geprüft 19.11.2026)
- 192 Videos in 43 Ordnern, alle Hochformat (Nacht Outfit Clips 1176x1760 statt 1176x1764, nicht sichtbar).
- 20 Dateien sind exakt doppelt (meist mit "(1)" oder "(2)" im Namen), 7 Ordner sind leer. Es wird nichts ohne Metin verschoben oder gelöscht.
- Unklare Einordnungen werden mit Metin besprochen, nicht selbst entschieden.

### Grundschleifen
- "Zeit. Glück" = glückliche Grundschleife (liest, lächelt, posiert leicht), "Schleife" bzw. "Zeit. Traurig" = traurige Grundschleife. Sie laufen, wenn nichts Besonderes passiert (bestätigt von Metin).
- Bestand glücklich: langes Kleid 11 verschiedene, kurzes Kleid 3 verschiedene (zu wenig, 3 bis 5 mehr wären gut). Zu viele können für andere Kategorien genutzt werden.

### Traurige Clips, Einordnung (mit Metin bestätigt, 19.11.2026)
- Langes Kleid: alle Clips aus "Schleife .Traurig. L. Kleid" und "Traurig langes Kleid" sind traurige Grundschleifen (11 verschiedene), außer 20261118_172906603 (dreht sich weg) = "sauer, wegdrehen".
- Kurzes Kleid: die ruhigen Clips aus "Traurig kurzes Kleid" und "Zeit. Traurig. K. Kleid" sind traurige Grundschleifen. 20261118_164614017, 20261118_165441215, 20261118_170730371 (dreht sich weg, wirft die Haare zurück) = "sauer, wegdrehen". 20261117_053920645 ist derselbe Clip wie in "Setzen". 20261118_104219278 zeigt das lange Kleid und liegt falsch im Ordner des kurzen Kleids.
- Stufen: ruhige Schleifen = leicht bis mittel, die knienden Clips aus "Setzen" = schwer.

## Noch offen
- Metins Kategorienliste (er prüft gerade die Einordnung).
- Woran genau sich die Gefühle ändern: Liste der Alltagsszenarien mit Gewicht.
- Wie Geschenke ausgelöst werden (Knopf in der App oder nur gesagt), was realistisch machbar ist.
- Wie lange Funkstille dauert, bis sie ihn vermisst.
- Umziehen: Szene für den Kleiderwechsel in beide Richtungen.
- Ob die Gefühle auch im Gespräch zu Hause (Voice PE) gelten.
- Überraschung: später erweitern (Metin, 19.11.2026).
