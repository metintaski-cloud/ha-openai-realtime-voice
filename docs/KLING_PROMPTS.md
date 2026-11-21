# Kling Prompts (Standard seit 21.11.2026)

Ergebnis der Recherche vom 21.11.2026 (Metin: "Kling macht was es will"). Gilt für alle Leyla und Mokka Clips. Ersetzt den alten Standard vom 16.11.2026 (lange Grundregeln vorne im Prompt).

## Warum Kling nicht gehorcht

1. Zu lange Prompts: Kling gewichtet den Anfang am stärksten und verliert ab etwa 80 Wörtern den Faden. Grundregeln vorne verdrängen den Ablauf.
2. Zu viele Handlungen: mehr als eine Handlung pro 2 bis 3 Sekunden wird nicht sauber umgesetzt. Bei 10 s vergisst Kling ab etwa Sekunde 7 oft das Ende (Mokka legte sich nicht hin).
3. Verbote im Prompt wirken schwach: sie gehören ins Negativ Feld, höchstens 12 bis 15 Begriffe.
4. Ohne Endbild rät Kling das Ende. Start und Endbild sollen sich im Aufbau stark ähneln.

## Gemessen am besten

- 5 s statt 10 s: 85 % saubere Clips gegen 55 %. Zwei 5 s Clips (letztes Bild von Clip 1 = Startbild von Clip 2) besser als ein 10 s Clip.
- Sichtbare Bewegung beschreiben ("hebt die Pfote und leckt sie"), keine Stimmung; immer mit ruhiger Endhaltung enden.
- "static background, locked-off camera" für stillen Hintergrund und feste Kamera.
- Standard zum Testen, Professional für den fertigen Clip (Haare, Stoff); 3 bis 5 Versionen, die beste nehmen.

## Neues Format

1. Prompt kurz (unter 80 Wörter): zuerst der Ablauf mit Sekunden ("0 to 2 seconds: ..."), am Ende nur noch `static background, locked-off camera, whole body in frame, portrait format like the start image`. Kleid oder Outfit nicht beschreiben, kommt aus dem Bild.
2. Negativ Feld: `camera movement, zoom, cuts, text, watermark, flickering, morphing, extra limbs, sliding feet, floating, reflection, new lights, background motion` (je nach Clip anpassen, höchstens 15 Begriffe).
3. Eine Handlung pro 5 s Clip, immer mit Start und Endbild (Schleife: Start = Ende; Übergang: Endbild der Zielpose).
4. Längere Abläufe als Kette mehrerer 5 s Clips, z. B. Mokka: reinlaufen, hinsetzen, hinlegen.

## Vertieft (21.11.2026, zweite Recherche)

- Regler "Creativity / Relevance" ganz Richtung Relevance stellen und Professional nehmen: dann hält sich Kling am stärksten an Bild und Prompt.
- Im Prompt nur Bewegung beschreiben, nie Aussehen (auch die Katze nicht): Beschreibungen von Fell, Kleid, Haaren lassen Kling das Motiv neu erfinden und überschreiben.
- Startbild: scharf, mindestens 1024 px an der kurzen Seite, schon im Hochformat zugeschnitten. Das Motiv sollte groß im Bild sein; ein kleines Motiv (Mokka) gibt Kling wenig Halt, deshalb verformt es sich leichter.
- Wenig Bewegung zuerst; zu viel Bewegung verformt das Motiv.
- Motion Brush: bis zu 6 Bereiche mit eigener Bahn; die Bahn gibt an, wo das Element am Ende steht (z. B. Mokka von rechts zu ihrem Platz). Static Brush auf alles, was still bleiben soll (Leyla, Hintergrund, Boden), das hält auch die Kamera fest. Nur Dinge mit Bahn versehen, die sich wirklich bewegen können, sonst wird es als Kamerafahrt gelesen.
- Prüfen: das erste Bild des Clips muss genau dem Startbild gleichen; wenn nicht, Relevance höher.
- Kling 4.0 (seit Oktober 2026 für alle): 3 bis 30 s, bis zu 10 Keyframe Bilder pro Clip, Start und Endbild, Omni Reference mit bis zu 15 Vorlagen (Bilder, Videos), Verlängern fertiger Clips. Für Abläufe mit mehreren Schritten (reinlaufen, hinsetzen, hinlegen) eine Keyframe Pose pro Schritt setzen statt alles im Text; trotzdem mehrere Versionen einplanen, keine geprüften Tests bekannt.

## Start und Endbild im Detail (21.11.2026, dritte Recherche)

- Vor dem Schreiben beide Bilder vergleichen (Position, Pose, Umgebung, Blickwinkel, Licht) und im Prompt nur beschreiben, was den Unterschied verursacht. Nichts schreiben, was einem der beiden Bilder widerspricht (z. B. "liegt" im Text, aber sitzt im Endbild).
- Schleife (gleiches Bild als Start und Ende): nur für Bewegungen, die von selbst zurückkehren (atmen, wiegen, schauen, kleine Gesten). Gehen, Hinsetzen oder Wegdrehen kann nicht ohne Sprung zum Start zurück, dafür Übergangsclips mit eigenem Endbild.
- Je ähnlicher Start und Ende, desto kürzer der Clip; je größer der Unterschied (Pose ändert sich), desto mehr Zeit geben. Ein Clip soll nur einen Unterschied überbrücken.
- Kamera muss fest sein, sonst passt das Ende nie zum Start; Bewegung im Nachhinein lässt sich kaum flicken, dann neu machen.
- Licht und Farbe können über den Clip wandern und am Übergang flackern; deshalb Licht nicht ändern lassen und keine neuen Lichter.
- Kling 4.0 Keyframes: Zwischenposen als eigene Bilder in der richtigen Reihenfolge hochladen (keine Collage in einem Bild), die Übergänge zwischen ihnen im Text beschreiben; Sekundenangaben sind Wünsche, nicht bildgenau.
- Was Kling trotzdem verfehlt, retten wir im Schnitt: Schnitt am Bild, das dem Start am ähnlichsten ist (`tools/mkclip.py`), kurzes Überblenden in die Grundpose, Prüfung von Anfang und Ende gegen die Grundpose (Messung wie am 21.11.2026).

Quellen dritte Recherche: aitoolsguidebook.com/en/articles/ai-video-loop-not-seamless, photogptai.com/guides/how-to-prompt-kling-4-video-model, insmind.com (start end frame).

Quellen: dev.to/neuraitool (Kling 4.0 explained), blog.mean.ceo/kling-news-november-2026, aitoolsguidebook.com (image to video not following), kling.ai/quickstart/how-to-animate-image-parts, youart.ai/blog/kling-4-0-prompt-guide, screenweaver.ai/blog/prompting-kling-guide, pexo.ai/blog/kling-ai-tips-better-results-8652, insmind.com/blog/smooth-ai-video-transitions-kling-start-end-frame, veed.io/learn/kling-ai-prompting-guide.

## Profi Quellen (21.11.2026, vierte Recherche): offizielle Kling Anleitungen haben Vorrang

Die offiziellen Anleitungen von Kling (kling.ai/quickstart) widersprechen in zwei Punkten den Ratgebern von Drittseiten. Was offiziell ist, gilt:

**Kling 4.0 (offiziell)**
- Modus "Keyframes" (nur Bilder): erstes Bild, erstes und letztes Bild oder bis zu 10 Bilder an beliebigen Zeitpunkten, mit pixelgenauer Treue zu den Bildern. Nicht mit Omni Reference kombinierbar.
- Schreibweise: "Use @Image1 as the first frame and @Image2 as the last frame", danach den Ablauf dazwischen. Bilder werden in Hochladereihenfolge nummeriert.
- Mehrere Einstellungen (Multi Shot) sind standardmäßig an: deshalb immer "a single continuous shot with no cuts" in den Prompt.
- Kein eigenes Negativ Feld; Verneinungen können Fehler sogar erhöhen. Positiv beschreiben, was passieren soll ("the camera stays perfectly still on a tripod", "her paws stay planted on the floor"); höchstens wenige Ausschlüsse wie "no subtitles, no watermark, no music".
- Ausführliche, konkrete Prompts werden genauer befolgt; aufbauen als: Rolle jedes Bildes, Grundeinstellung (Szene, Kamera), Ablauf nach Zeitabschnitten, Ton. Keine abstrakten Wörter ("edel", "vintage").
- Länge 3 bis 30 s, Standard 10 s; Seitenverhältnis folgt dem ersten Keyframe; 720p, 1080p, 4K. Flash: schneller und billiger, nur 720p und bis 20 s, zum Testen.
- Fehler wachsen mit der Länge: lieber kürzer und mit Keyframes für die wichtigen Posen.

**Ältere Modelle (2.x, 3.0) mit Negativ Feld**: dort gilt weiter das Format oben (kurzer Prompt, Verbote ins Negativ Feld, 5 s pro Handlung).

**Motion Control (offiziell, VIDEO 2.6 und 3.0)**: überträgt Bewegung aus einem echten Video auf eine Figur im Bild. Empfohlen für echte Menschen, also für Leyla (z. B. ein Tanz aus einem Referenzvideo), nicht für Mokka. Referenzvideo: eine Person, ganzer Körper sichtbar, ein durchgehender Take ohne Schnitt und ohne Kamerabewegung, ruhige Bewegung; Bild im gleichen Ausschnitt (ganzer Körper). Kosten 3.0: 12 Credits pro Sekunde Professional, 9 Standard.

**Profis (Curious Refuge, Kling Blog)**: Endbild nur mäßig anders als das Startbild; Schleife mit identischem Bild; keine Schrift in die Bilder; ein Master Bild immer wieder als Vorlage nutzen; Kamera mit Stativ Wörtern festnageln ("fixed lens, tripod").

Quellen vierte Recherche: kling.ai/quickstart/kling-4-model-user-guide, kling.ai/quickstart/motion-control-user-guide, kling.ai/blog/fix-ai-video-drift-consistency-guide, curiousrefuge.com/blog/8-ways-to-use-first-frame-last-frame-in-your-ai-videos.

## Profi Tests und Feinheiten (21.11.2026, fünfte Recherche)

- Unerwünschte Schnitte: Multi Shot ist an. Den Prompt mit "a single continuous shot with no cuts" beginnen und nie zwei Bildgrößen nennen (z. B. "wide shot ... close up"), das löste im Test einen harten Schnitt aus.
- Kamera fest: nur eine Bildgröße am Anfang nennen ("full body shot") und keine Bewegungswörter. Diese Wörter lösen Kamerabewegung aus: pan, tilt, zoom, dolly, orbit, crane, spin, tracking, following, steady (meint Steadicam), handheld, aerial.
- Start und Endbild in Kling 4.0: im Test einwandfrei, sowohl ein 10 s Clip als auch zwei verkettete 5 s Clips ohne Verformung; beim Verketten nur der Ton am Übergang hörbar, 4 bis 6 Bilder Ton Überblendung.
- "no text" verhindert keine Schrift auf Gegenständen; Flächen als schlicht und unbeschriftet beschreiben.
- Flash hält Farben gut und ist billig, verfehlt aber eher Abstände und Bewegungen; Kling 3.0 driftete im Test im Licht und ließ Bewegungen weg. Für die finalen Leyla Clips Kling 4.0.
- Elemente (Leyla immer gleich): ein Element pro Outfit aus bis zu 4 Bildern (vorne, seitlich, hinten, Detail Gesicht), gleichmäßig ausgeleuchtet; Schalter "Bind Subject to Enhance Consistency" an. Ein einziges Bild lässt Kling die unsichtbaren Seiten raten (z. B. beim Umdrehen).
- Referenzvideo für Bewegung (4.0 Omni Reference): im Prompt sagen, was es liefert und was nicht ("only the motion of @Video1, not its person or background"), kostet etwa 20 % mehr.

Quellen fünfte Recherche: chatcut.io/blog/kling-4-0-review, kling.ai/blog/kling-3-subject-binding-character-consistency, kling.ai/blog/ai-camera-control-movement-prompts-guide.

## Kosten sparen wie Profis (21.11.2026, Recherche)

- Jede Generierung kostet, auch die verworfenen; 4 Versionen auf einmal sind 4 Abrechnungen.
- Kling 3.0 Credits pro Sekunde: 720p ohne Ton 6, mit Ton 9; 1080p ohne Ton 8, mit Ton 12. Ein 5 s 720p Test ohne Ton = 30 Credits, ein 10 s 1080p Clip mit Ton = 120. Für Kling 4.0 gibt es im Abo noch keine veröffentlichte Credit Tabelle (API: 0,157 USD/s 720p, 0,235 USD/s 1080p): vor dem Start immer den angezeigten Preis prüfen.
- Ablauf: höchstens 3 bis 4 Tests mit 5 s, 720p, ohne Ton (Flash oder Standard); jeder neue Versuch repariert genau einen benannten Fehler; dann ein einziger finaler Render in 1080p.
- Ton nur, wo die App ihn abspielt (Kuss, Rose, Komm, I love you); bei allen anderen Clips Ton aus, das spart ein Drittel.
- 5 s statt 10 s halbiert den Preis; längere Abläufe als Kette von 5 s Clips.
- Was ich im Schnitt retten kann (Flackern, Ende in die Grundpose, Anfang kürzen), nicht neu generieren.
- Erfolgreiche Prompts aufheben und wiederverwenden (dieses Dokument und das Erfahrungslog).
- Abo: Jahreszahlung spart etwa 25 %; Monats Credits verfallen nach 31 Tagen, gekaufte Credit Pakete halten 2 Jahre (Kling verbraucht die bald ablaufenden zuerst); tägliche Bonus Credits bei der ersten Anmeldung am Tag, sie verfallen um Mitternacht.

Quellen: atlascloud.ai/blog/tips/kling-4-credit-burn-rate-workflow, aitoolanalysis.com/kling-ai-pricing, note.com/rich_emu7600 (Credits verschwinden).

## Bedienung über den Browser der Claude App (21.11.2026)

- Claude stellt Modus, Auflösung, Länge ein und tippt den Prompt; Bilder hochladen und Downloads speichern braucht Metins Hand, weil sich dabei Windows Fenster öffnen (Datei auswählen, Speichern unter: dort nur Enter drücken).
- Download einer 4K Datei (2352x3524, 24 fps, 10 s) war nur 6 MB groß.
- Medienordner ist seit 21.11.2026 auf Metins PC als Laufwerk Z: verbunden (\\192.168.2.240\media) und in der Claude App als Ordner freigegeben: Claude legt fertige Clips selbst nach Z:\leyla\<look>\, Metin muss nichts kopieren.
- Bilder für Keyframes: einmal hochgeladen, danach über "Asset" > "Uploads" oder "Extract Frames" (Bild aus einem fertigen Clip) wählbar, ohne Datei Fenster.
- Seit 21.11.2026 (Metin): wenn alles passt, klickt Claude ohne Nachfrage auf "Generate", bis Metin "stop" schreibt.
- Vor jedem "Generate" zeigt Claude Einstellungen und Credits und wartet auf Metins Okay.

## Metins Erfahrung (über 238 Clips)

Ein richtig guter Clip kommt meist erst nach etwa 4 Versuchen. Das ist die Arbeitsregel: pro Clip 4 Versuche einplanen (zum Testen mit Flash oder Standard), den besten nehmen und nur noch per Edit nachbessern.

## Erfahrungslog (jeder Clip von Metin)

Jeder neue Clip wird gemessen (Unruhe, Rucken, Anfang und Ende gegen die Grundpose) und hier mit Prompt, Einstellungen und Ergebnis eingetragen, damit wir aus echten Ergebnissen lernen und nicht nur aus Anleitungen.

| Datum | Clip | Modell, Modus, Länge, Bilder | Ergebnis | Lehre |
|---|---|---|---|---|
| 21.11.2026 | Mokka kommt (alt) | 10 s, nur Startbild, langer Prompt | Pfoten rutschen beim Hinsetzen | eine Handlung pro Clip, Motion Brush mit Bahn |
| 21.11.2026 | Mokka hinlegen | 5 s, Startbild mit sitzender Katze | kein Reinlaufen, alles gehetzt, Ende (liegt, Augen zu) gut | 5 s nur für eine Handlung; Endbild für das Hinlegen |
| 21.11.2026 | Mokka springt auf den Schoß (Metin) | 15 s, 5 Handlungen (springen, streicheln, runter, zurücklaufen, hinlegen), Verbote im Prompt | über 4 Versuche, alle schlecht, gelöscht | zu viele Handlungen für einen Clip; Verbote statt positiver Sätze |
| 21.11.2026 | Mokka kommt, sitzt, liegt | Kling 4.0 Keyframes (allein, sitzt, liegt), 4K, 10 s, 350 Credits, Versuch 1 | Katze beim ersten Versuch toll (echte Schritte, setzt sich, legt sich, Ende wie Keyframe); Leyla komplett eingefroren | gleiche Pose auf allen Keyframes plus "keeps her pose" friert eine Figur ein. Für Tiere nutzen wir das: Leyla und Bühne stehen still, Mokka wird per Differenz zum ersten Bild sauber ausgeschnitten und über die normalen Clips gelegt. Soll eine Figur leben, ihre Bewegung beschreiben und nicht dreimal dieselbe Pose geben |
