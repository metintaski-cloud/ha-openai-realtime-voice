# Kling Prompts

> **Zuerst lesen (Stand 23.11.2026):** Maßgeblich ist der Abschnitt "Profi Wissen Kling 4.0 (sechste Recherche, 23.11.2026)" weiter unten, samt der Tabelle "Was sich an unseren bisherigen Regeln ändert". Wo ein älterer Abschnitt dem widerspricht, gilt der neue. Metins Auftrag dazu: nur Profi Wissen aus offiziellen und professionellen Quellen, nichts selbst erfinden, und bei jedem Prompt offen sagen, welcher Teil aus den Quellen stammt und welcher aus unserem eigenen Log. Die Abschnitte davor bleiben als Verlauf und Erfahrungslog stehen.

## Alter Standard vom 21.11.2026 (Verlauf)

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
- Vor jedem "Generate" zeigt Claude Einstellungen und Credits und wartet auf Metins Okay (Metin schrieb am 21.11.2026 "stop", als ein Clip 525 Credits kostete).
- Keine Tests in niedriger Auflösung (Metin, 21.11.2026): Jeder Clip wird direkt in 4K erzeugt. Klings Video Upscaler (kling.ai/feature/video-upscaler, Video 3.0 Omni, bis 3840x2160) rechnet nicht 1:1 hoch, sondern erfindet Details; Gesicht und Kleidung können sich ändern.
- Einstellungen vor Generate prüfen (21.11.2026): Nach einem Neuladen der Seite stand die Länge plötzlich auf 5 s (175 Credits) statt 10 s; Metin hat es bemerkt. Claude liest vor jeder Freigabe den Text "4K · 10s · Adaptive · 1" am Einstellungsknopf und den Preis 350 am Generate Knopf.
- Favoriten (21.11.2026, Metin): Die Outfit Bilder für Start und Ende sind in Kling unter Asset > Uploads als Favoriten markiert und die Auswahl zeigt nur Favoriten; trotzdem vor Generate groß prüfen.
- Startbild Regel (seit 21.11.2026, nach einem 4K Loop für 350 Credits mit falschem Bild: Mokka lag mit im Clip): Die Reihenfolge unter "Uploads" ändert sich nach jedem neuen Bild, eine Position wie "Reihe 1, Bild 2" ist deshalb nie verlässlich. Direkt vor "Generate" vergrößert Claude die beiden Vorschaubilder "First frame" und "Last frame" im Eingabefeld (Zoom) und prüft am Bild selbst: richtiges Outfit, Katze nur dann sichtbar, wenn der Clip sie braucht. Erst wenn beide stimmen, nennt Claude Metin die Bilder mit Namen ("Start: Leyla allein, Ende: Leyla allein") zusammen mit den Credits.
- Tempo (21.11.2026): Prompts, in denen fast jede Bewegung "slowly" oder "slow and smooth" heißt, liefert Kling 4.0 wie in Zeitlupe. Metin wählte beim Po Clip "Schüchtern" nach Vergleich von 1,15 bis 2,0 die 1,7 fach beschleunigte Fassung (ffmpeg setpts=PTS/1.7, fps=24, 10 s werden knapp 6 s); das ist der Startwert für solche Clips. Ruhige 4K Schleifen (kurz/freizeitgluecklich2, schwarz/freizeitgluecklich3, 21.11.2026) wählte Metin mit 1,5 fach; Nahtstelle Anfang zu Ende nur 0,6 (früher etwa 1,0). Berührungs Clips mit "natural speed": Kopf 1,3 fach; Wange (schwarz/freizeitgesicht) vorne 1,3 fach, das Armsenken am Ende ab Sekunde 7 mit 1,8 fach, weil Kling das Zurückgehen in die Startpose sehr langsam macht (ffmpeg trim und concat). Schulter Shimmy (schwarz/freizeitbrust) wollte Metin im Originaltempo, 1,3 fach war ihm zu schnell: Tempo also immer pro Clip zur Auswahl geben. Ruhiger Anfang: Kling lässt die erste Handlung (z. B. "blushes shyly", 0 bis 2 s) oft zu lang stehen; Metin fand den Po Clip mit Achterkreis (schwarz/freizeitpo3) am besten, als nur die ersten 2,5 s mit 1,4 fach liefen und der Rest im Original (ffmpeg trim, concat, atempo); gleichmäßiges Verlangsamen mit errechneten Zwischenbildern wirkte zäh. Po "schau her mein Süßer" (kurz/po2, 21.11.2026): Versuch 1 mit "big swinging figure-eight" wackelte hektisch ohne Takt; Versuch 2 mit "in a slow, calm, steady rhythm she sways her hips just twice, each sway long and smooth, then holds still" war gut. Metin wollte nur das Hüftwiegen (Sekunde 3 bis 8) auf 0,75 verlangsamt, mit Bewegungsinterpolation (ffmpeg minterpolate mi_mode=mci), Dreh und Ende im Original. Po langes Arbeitskleid (schwarz/po2): Prompt mit "leans forward slightly and pushes her hips back toward the camera with an arch in her back"; von zwei Versuchen drehte sich nur einer ganz mit dem Rücken zur Kamera. Metin wollte ab Sekunde 3 alles gleichmäßig 0,85 (mci), auch den letzten Schwung mit Anlauf und das Zurückdrehen; Schnittgrenzen mitten in einer Bewegung wirken falsch, lieber ab Beginn der Po Bewegung bis zum Ende durchgehend verlangsamen. Steifer Shimmy: "rolls her shoulders" bewegt nur die Schultern; besser "quick, loose shoulder shimmy, her whole upper body moves naturally and fluidly" plus "natural, realistic body physics". Neue Prompts schreiben "natural speed" und nur einzelne Bewegungen "slowly". So geht die Prüfung sicher: die Vorschaubilder im Uploads Fenster und im Eingabefeld sind zu klein (eine liegende Katze ist dort nur ein grauer Fleck), deshalb blendet Claude sie per JavaScript bildschirmfüllend nebeneinander ein, mit der Klickposition als Beschriftung, und entfernt die Einblendung danach wieder. Am 21.11.2026 war das Bild ohne Katze in Uploads oben rechts (Reihe 1, Bild 5); der Po Clip "Schüchtern" lief ebenfalls zuerst mit dem Katzenbild und wurde neu gemacht.

- Fremde Hand (21.11.2026, Kopf Clip langes Arbeitskleid): Der Prompt "she feels a gentle stroke on her head ... as if someone is stroking her hair" ließ Kling eine fremde Hand von oben ins Bild malen. Bei Berührungs Clips nie eine andere Person, ein "someone" oder eine streichelnde Hand erwähnen; nur Leylas eigene Reaktion beschreiben ("she closes her eyes and tilts her head slightly, smiling blissfully"). Bei Po, Brust und Bauch gilt dasselbe.

Ab 21.11.2026 (Metin): Bei wichtigen Clips gleich zwei Versuche mit demselben Prompt erzeugen und den besseren nehmen; derselbe Prompt lieferte beim Po im langen Arbeitskleid einmal eine volle Drehung und einmal nur seitlich.

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


## Po Nacht "Clubtanz" (21.11.2026, nacht/po7)

Prompt wie Freizeit Po, aber 3 bis 8 s: "she dances with her back to the camera, swaying her hips from side to side on a steady, slow beat like to a sensual R&B song, each sway smooth and even ... keeps glancing back over her shoulder at the camera with a flirty smile". Ergebnis traf Metins Wunsch beim ersten Versuch. Tempo: erste 3 s original, ab 3 s 0,76 mit mci Interpolation und atempo (0,92 bis 0,8 waren ihm zu schnell).

Freizeit (21.11.2026): Derselbe Clubtanz Prompt gab im kurzen Freizeitkleid sofort einen guten Clip (kurz/freizeitpo9, ab 3 s 0,94), im langen Freizeitkleid aber zwei schnelle Drehungen mit fliegenden Haaren (hektisch); gerettet durch abschnittsweise Bremsen nur der Drehungen (schwarz/freizeittanz2). Für schnelle Bewegungen nur leicht bremsen (0,94), 0,76 war für Freizeit zu langsam.

## Musikrichtung im Prompt

Die genannte Musik bestimmt den Bewegungsrhythmus, auch wenn kein Ton erzeugt wird: "like to a sensual R&B song" gab einen gleichmäßigen Clubtanz. Für orientalischen Hüftschwung "on a steady oriental drum rhythm" und "belly dance" nennen; ohne Musikrichtung ("gently swaying her hips") kam nur leichtes Wippen (Hüftschwung Schleife lang Freizeit, erster Versuch).

## Bauchtanz (22.11.2026, schwarz/freizeittanz3)

Prompt Kern: "she dances an elegant, sensual oriental belly dance in place. Her upper body and shoulders stay calm and upright while her hips swing wide and fluidly from side to side, drawing smooth figure eights and soft hip drops on a steady oriental drum rhythm ... Her arms float softly and gracefully at her sides like a belly dancer". Erster Versuch sauber, Metin: schön, mehr davon. Als Schleife zu unruhig, deshalb als Tanz.

## Erfundene Brille (22.11.2026)

Kling setzte im kurzen Freizeitkleid beim Blick über die Schulter eine Brille auf, obwohl Start und Endbild keine zeigen (vermutlich aus den Arbeitsbildern gelernt). Zweiter Versuch mit "She never wears glasses" brachte trotzdem kurz eine Brille in der Drehung: Das Wort selbst kann die Brille erst hervorrufen (Kling folgt positiven Beschreibungen, Verneinungen wirken schlecht). Deshalb das Wort glasses nicht schreiben, sondern positiv "Her bare face, eyes and hair stay exactly as in the keyframes the whole time"; Gesichter im Kontaktbogen gezielt auf Brille prüfen. "Edit Video" zum Entfernen kostet in 4K 420 Credits, mehr als ein neuer Clip.

## Gleicher Takt für alle Bauchtänze (22.11.2026)

Die Tänze laufen in der App hintereinander, deshalb müssen alle Bauchtänze im selben Rhythmus schwingen. Messung: horizontaler Schwerpunkt der Hüftzone pro Bild, dann die stärkste Frequenz (FFT) zwischen 0,2 und 3 Hz. Maßstab ist Clip 1901 (Nacht) im Originaltempo mit 0,68 Schwüngen pro Sekunde (Metin: "dieses Tempo am liebsten überall"); Faktor für jeden anderen Clip = 0,68 / eigene Frequenz (nacht/tanz12 0,675, schwarz/freizeittanz3 0,87, kurz/freizeittanz 0,787). Gleichmäßig über den ganzen Clip bremsen, mit mci Interpolation. Ein schon langsamer Clip sah bei 0,89 gebremst schlechter aus als im Original: Clips mit gutem Eigentakt lieber als Maßstab nehmen und die anderen anpassen. Für alte Tänze ohne festen Takt geht das nicht.

## Nachbau kurz/tanz8 und tanz9 für Nacht und Freizeit (geplant 22.11.2026)

Metin: "unbedingt 1:1" für Nacht, kurz Freizeit und lang Freizeit (6 Clips). Ablauf der alten Clips (14 s, auf 10 s verdichtet):
- tanz8: 0 bis 1,5 s Drehung mit dem Rücken zur Kamera; 1,5 bis 8 s weite, gleichmäßige Hüftschwünge von Seite zu Seite, Arme schwingen locker, Kopf bleibt nach vorne; 8 bis 10 s Drehung zurück in die Startpose.
- tanz9: wie tanz8, aber die Hüfte wird deutlicher nach hinten geschoben, sie beugt sich leicht vor und streckt einen Arm zur Seite, kurzes Wippen in der Mitte.
Prompts ohne Buch und ohne das Wort glasses ("Her bare face ... stays exactly as in the keyframes"), Musikrichtung nennen; danach auf den Bauchtanz Takt prüfen.

## R&B mit Darbuka (22.11.2026, kurz/freizeittanz2)

Prompt Kern: "she dances in place to a slow, sensual R&B groove blended with Arabic darbuka drums, moving like a belly dancer: her hips sway wide and smoothly from side to side with soft hip drops on each drum beat, her upper body stays calm, her arms float gracefully". Kling tanzte trotzdem recht schnell (1,1 Schwünge pro Sekunde); auf 0,62 gebremst wirkten Gesicht und Mimik träge, Metin nahm 0,75. Nächstes Mal "slow, elegant" direkt in den Prompt, damit weniger gebremst werden muss.

## Rückenansicht wie tanz8/9 (22.11.2026)

Musikrichtungen (arabische Trommeln, R&B) brachten nur Tanzbewegungen mit schwebenden Armen, nicht die Haltung von tanz8/9 (sieben Versuche, rund 2.450 Credits). Am nächsten kam ein Prompt ohne Musik, der nur den Körper beschreibt (Clip 2634, nacht/tanz20): "with her back to the camera and her feet together on the same spot, she lets her arms hang down long, straight and relaxed beside her body. Slowly and smoothly her whole body moves in a soft serpentine wave: the wave starts at her shoulders, flows down through her waist into her hips, her hips swing out to one side and then the other, and her knees bend so that she sinks lower in a slow curving motion; then the wave flows back up ... as she rises again to full height. She repeats this ... twice". Metins Hinweis: genau beschreiben, keine Musiktanz Art. Alternative für echtes 1:1: Motion Control mit dem alten Clip als Vorlage.

## Gesichtsausdruck abwechseln (22.11.2026)

Metin: Leyla guckt überall gleich, sehr monoton, keine schüchternen Blicke. Ursache: fast jeder Prompt hatte "warm smile" oder "flirty smile". Regel: in jedem Clip einen anderen, konkret beschriebenen Ausdruck, gern mit Wechsel innerhalb des Clips, zum Beispiel shy (eyes lowered to the floor, bashful smile, slowly lifts her gaze), mischievous (one eyebrow slightly raised), dreamy (half closed eyes, soft smile), laughing, sultry (slow look, lips slightly parted), surprised. Nie zweimal hintereinander denselben Ausdruck.

## Kamerabewegung (22.11.2026)

Metin will Zoom und Kamerabewegung. Regel: Die ersten und letzten 1 bis 1,5 s zeigen das Ganzkörperbild genau wie die Keyframes (sonst springt das Bild beim Übergang zum nächsten Clip); dazwischen z. B. "the camera slowly pushes in to a medium shot from the hips up ... then slowly pulls back to the full body framing of the keyframes" oder ein leichter Bogen zur Seite und zurück. Den Satz "the camera stays perfectly still on a tripod" dann weglassen.

## Rose Versöhnung (22.11.2026, schwarz/freizeitrose2, Metin: "Hammer")

Keyframes: Start ein eigens erstelltes trauriges Bild (gleiche Pose und Outfit, feuchte Augen), Ende das lächelnde Favoritenbild. Prompt Kern: "She is the only person visible; of the giver only one man's hand is seen, nothing else of him." Kamera: "starts on the full body framing ..., slowly zooms in to a close-up of her face by 2.5 seconds, holds on her face, then slowly tilts down and widens to frame her from the head down to the knees by 6.5 seconds, and from 8.5 seconds on it holds exactly the full body framing of the last keyframe again." Gefühle Schritt für Schritt: traurig, Blick gesenkt, leises Schniefen; zögernder Blick zur Rose; zitterndes kleines Lächeln, Träne wegwischen; an der Rose riechen, Traurigkeit schmilzt; dankbares, schüchternes, wachsendes Lächeln. Ende: Rose hinter die Hüfte senken. Bei fröhlichen Rosen keine Freudentränen schreiben (wirken traurig). Für traurige Szenen eigene traurige Keyframes erstellen, statt vom lächelnden Bild auszugehen.

Rose 20 s (kurz/freizeitrose2, Clip 2940, Metin: "Hammer"): "filmed from the point of view of the man giving the rose ... of him only his hand is seen, never his arm, sleeve or body ... only a man's hand rises into view at the bottom center of the frame, directly in front of the camera". Sie geht zur Kamera, holt die Rose, Nahaufnahme, dann mit dem Rücken zur Kamera glücklich zurück an ihren Platz, Blick über die Schulter. 20 s kosten 700 Credits; die Dauer danach wieder auf 10 s stellen.

Zu harte Bewegungen (Clip 2923, wilder Trommelsolo Prompt): tiefe breitbeinige Hocke, ruckartige Haarwürfe. Metin will "wild aber sehr feminin": "every movement round, soft, flowing and graceful, never angular or harsh; she stays upright and light on her feet".

## 20 s Tanz "wild aber feminin" (22.11.2026, nacht/tanz27, Metin: "MEGA")

Kern: "She performs a passionate, fiery yet very feminine oriental belly dance: full of energy and temperament, but every movement round, soft, flowing and graceful, never angular or harsh; she stays upright and light on her feet, always elegant like a professional belly dancer, to a lively Arabic darbuka rhythm." Abschnitte: Doppeldrehung, Rückenansicht mit Kamera tief an der Hüfte (Shimmy, Kreise, Achten), Kamera schwenkt hoch zur Nahaufnahme (Haare über die Schulter, glühender dann schüchterner Blick), Drehung zur Front mit Schlangenarmen, Temperamentschub (Shimmy, Bauchwellen, Hüftdrops), seitlich Kamelwelle, letzte Drehung. Kling hielt sich nicht ganz an "upright" (kurze Hocke), Metin gefiel es trotzdem.

## 20 s Tanz "weich feminin" (22.11.2026, nacht/tanz30, Clip 2966, Metin: "sehr gut gemacht")

Nachfolger des wilden 20 s Prompts mit weicheren Bewegungen. Kling lieferte ihn schnell (1,47 Hüftschwünge pro Sekunde). Nachbearbeitung: Tanzteil 0 bis 16,5 s auf 0,75 (minterpolate mci), der ruhige Schluss ab 16,5 s im Originaltempo. Regel: Ist das Ende eines Clips schon ruhig, nur den schnellen Teil bremsen, sonst wirkt der Schluss träge (Metin: "am Ende wird es sehr langsam").

## 20 s Tanz "so weiblich wie möglich, slow und wow" (22.11.2026, Prompt gestartet 05:34)

Metin wollte nach Clip 2966 dasselbe mit mehr Rundungen, deutlich weiblicher und langsamer. Keyframes: Start und Ende das Nacht Favoritenbild (7_nacht.png). 4K, 20 s, Adaptive, 700 Credits. Prompt:

"Use the first keyframe as the first frame and the last keyframe as the last frame. A single continuous shot with no cuts. Her face stays bare, exactly as in the keyframes. She performs a slow, sensual, extremely feminine oriental belly dance to a slow, hypnotic Arabic darbuka and oud rhythm. Every movement is big, round, soft and flowing like honey, never fast, never angular or harsh; she stays upright, elegant and light on her feet like a professional belly dancer. Natural, realistic body physics. 0 to 3 seconds: full body framing exactly as in the first keyframe. She lowers her eyes shyly, then lifts her arms in soft snake waves above her head while her hips begin wide, round circles in a calm, steady rhythm. 3 to 7 seconds: she turns unhurriedly to show her back and glances over her shoulder with a dreamy, half closed look. The camera glides in low to hip height while her hips draw large, smooth figure eights, each curve long and round. 7 to 11 seconds: the camera rises along her back to a close-up of her face over her shoulder; she sweeps her long hair aside with one hand, her look sultry with lips slightly parted, then melting into a bashful little smile as she lowers her eyes. 11 to 15 seconds: she turns to the side and the camera pulls back to frame her from the knees up. In profile she rolls a slow, deep body wave from her chest down to her hips, twice, her arms floating softly beside her. 15 to 18.5 seconds: she turns back to the front with one graceful full turn, her hair flowing, her hips circling once more, and settles into the pose of the last keyframe with a warm, tender look, while the camera returns to the full body framing. 18.5 to 20 seconds: she holds the pose of the last keyframe and the camera holds exactly the full body framing of the last keyframe."

Ergebnis (Clip 3207, nacht/tanz31): Metin "wow, gut geworden". Kling hielt sich an Ablauf und Blicke, aber nicht an "slow": 1,32 Schwünge pro Sekunde, deshalb auf 0,8 gebremst (mci). Lehre: Tempo Wörter im Prompt bremsen einen Tanz zu Trommelmusik kaum, das Bremsen passiert in der Nachbearbeitung.

## Rose Arbeit, 20 s (22.11.2026, gestartet 05:38 und 05:39)

Metin: "die Blicke sind sehr wichtig, Emotion", "Rose Mitte Kamera bleibt". Keyframes: Start je ein von Metin erstelltes trauriges Bild im Arbeitskleid (mit Brille und Buch), Ende das lächelnde Favoritenbild (6_kurz_arbeit.png, 5_lang_arbeit.png). Je 4K, 20 s, Adaptive, 700 Credits, Ton bleibt. Gemeinsamer Anfang beider Prompts: "A single continuous shot with no cuts, filmed from the point of view of the man giving the rose. She is the only person visible; of him only his hand is seen, never his arm, sleeve or body. She keeps her book in her left arm the whole time. Natural speed, natural, realistic body physics; every emotion is clearly readable in her eyes and face." Hand: "only a man's hand holding a single red rose rises into view at the bottom center of the frame, directly in front of the camera". Ende: "lowers the rose behind her hip out of sight and settles exactly into the pose of the last keyframe".

- Kurzes Arbeitskleid (sie kommt zur Kamera): traurig, Augen am Boden, Lippen zusammengepresst, Schniefen; bemerkt die Rose aus dem Augenwinkel, zögernder Blick, große Augen; kleine Schritte zur Kamera bis Hüfte aufwärts, Blick von der Rose in die Kamera "searching and vulnerable, her eyes glistening", zitterndes Lächeln, nimmt die Rose; Nahaufnahme: riecht mit geschlossenen Augen, "warm, grateful, shy look, softly bites her lower lip, blushes"; geht mit dem Rücken zur Kamera zurück, "playful, loving look" über die Schulter.
- Langes Arbeitskleid (sie bleibt am Platz, die Kamera fährt zu ihr): "hurt and pouting", dreht den Kopf beleidigt weg; schielt zur Rose, schaut trotzig wieder weg; Kamera auf Hüfte aufwärts, "tiny reluctant smile that she tries to hide"; Nahaufnahme, nimmt die Rose, "shakes her head slightly as if to say she cannot stay angry, and breaks into a soft, shy laugh"; drückt die Rose an die Brust, riecht daran, Blick über die Blüte "loving, sparkling", Kamera fährt zurück.

Ergebnis: beide auf Anhieb gut (Clips 3221 und 3226), nur die Hand im Bild, Blicke von traurig über zögernd zu glücklich deutlich lesbar; gespeichert mit Ton im Originaltempo als kurz/rose4 und schwarz/rose3. Beim langen Kleid hat Kling das beleidigte Wegdrehen nur angedeutet.

## Bodenarbeit abgelehnt (22.11.2026)

Metin fragte nach Bodenarbeit wie in arabischen Tanzszenen. Der 20 s Prompt im Nacht Outfit ("sinks gracefully down onto her knees", "leans back in a deep, elegant backbend until her shoulders and her hair rest on the floor", "lies propped on one elbow") endete mit "Task generation failed. Credits returned." Kling lehnt Liegen und Zurücklehnen im Nacht Outfit also ab; nicht wiederholen.

## Zeig dich für die Tages Outfits (22.11.2026)

Metin: langsam, feminin, seitlich, hinten und vorn, sie spielt mit ihren Haaren und wirft schüchterne Blicke. 4K, 10 s, 350 Credits je Outfit, Kamera fest (Start und Ende dasselbe Favoritenbild). Prompt kurzes Arbeitskleid: "The camera stays perfectly still on a tripod and keeps the full body framing of the keyframes. She keeps her book in her left arm the whole time. She presents herself to the camera in a calm, unhurried and very feminine way, every movement soft and graceful. 0 to 2 seconds: ... lowers her eyes shyly with a bashful little smile and lifts her right hand to play with a strand of her long hair. 2 to 4.5 seconds: she turns slowly to the side and holds the side view for a moment, twirling the strand of hair around her finger, and glances shyly at the camera from the corner of her eye. 4.5 to 7 seconds: she turns on to show her back, sweeps her long hair over one shoulder with her right hand and looks back over her shoulder with a shy, warm glance, then lowers her eyes again. 7 to 9 seconds: she turns unhurriedly back to the front, running her fingers through her hair. 9 to 10 seconds: she settles exactly into the pose of the last keyframe and looks up into the camera with a shy smile."

Geändert um 06:05 (Metin): nicht Arbeit, sondern Freizeit und Nacht (Arbeit nur, wenn Credits übrig bleiben); 20 s statt 10 s (700 Credits); "so weiblich wie möglich mit super kurvigen Posen"; von hinten eine geschmeidige Achterbewegung; sie spielt mit ihrer Strähne. Gestartet für das kurze Freizeitkleid (Start und Ende 1_leyla_allein.png). Kern des Prompts: "She presents herself to the camera like a model, as feminine as possible, in calm, unhurried, flowing movements; every pose is a soft S-curve that shows off her curves, with her weight on one leg, one hip pushed out and a gentle arch in her back. She stays at her place." Abschnitte: 0 bis 3 s schüchtern, Gewicht auf ein Bein, spielt mit einer Strähne; 3 bis 6,5 s Seitenpose ("one hand on her hip, her back gently arched, her chest lifted and one knee softly bent"), Strähne um den Finger, Blick aus dem Augenwinkel; 6,5 bis 11,5 s Rücken, Haare über die Schulter, "her hips draw one long, smooth, supple figure eight in a calm rhythm", Hüfte raus, schüchterner Blick über die Schulter, beißt sich auf die Lippe; 11,5 bis 15 s Drehung nach vorn, Kamera zur Nahaufnahme, Strähne hinters Ohr, Blick "from under her lashes", wird rot; 15 bis 18,5 s Kamera zurück, letzte kurvige Pose; 18,5 bis 20 s Endpose.

## Süße Eifersucht und sauer (22.11.2026, Metin: "Rücken drehen sehr wichtig", "wirft die Haare nach hinten")

20 s, 4K, 700 Credits, Start und Ende dasselbe Bild mit ernstem oder traurigem Gesicht (von Metin erstellt), Kamera fest, dadurch echte Schleife. Alle drei Versuche auf Anhieb gut (Clips 3453, 3469, 3473). Kern: "She is sweetly jealous and sulky angry the whole time, in a cute, very feminine way, and never smiles." Bausteine: "narrows her eyes at the camera, puffs out her cheeks for a moment and presses her lips into a cute pout"; "stamps one foot lightly, lifts her chin and tosses her long hair back over her shoulder with a proud, offended flick of her head"; "turns around and shows the camera her back"; "looks back over her shoulder with a narrow, jealous glance ... turns her head away again with a little huff and tosses her hair back once more"; "peeks over her shoulder a second time to check whether he is still looking ... quickly looks away again when she is caught"; Ende "settles exactly into the pose and the serious expression of the last keyframe". Variante langes Kleid: "hugs her book tighter against her chest, lifts her nose proudly", "turns around with a proud swing of her dress ... giving him the cold shoulder", "shrugs one shoulder".

## Zeig dich: Ergebnis (22.11.2026)

Clips 3355 (kurz Freizeit), 3351 (lang Freizeit), 3461 (Nacht) gut bei Strähne, Seitenpose, Nahaufnahme mit rotem Gesicht. Die Hüft Acht von hinten kam in keinem Versuch deutlich: mit vier Handlungen im Rückenteil ließ Kling sie weg, mit "does only one thing ... her arms relaxed at her sides" stand sie steif da (Clip 3417). Für den nächsten Versuch: Hände in den Haaren oder an der Hüfte und "a big, wide figure eight, her hips swinging far out to each side".

## Lippenbiss setzt Kling nicht um (22.11.2026, kurz/freizeitgesicht)

Zwei Versuche mit demselben Ziel ("she bites her lower lip"), der zweite mit vier Sekunden nur für den Biss und mit Zähnen, Lippe und Richtung ausführlich beschrieben: In beiden Clips kein Biss, sie lächelt durchgehend mit geschlossenen Lippen (Bild für Bild geprüft bei 2,5, 3,5, 4,5 und 5,5 s). Beide gelöscht. Lehre: Lippenbiss gehört zu den Gesten, die Kling 4.0 nicht liefert; stattdessen Zwinkern, Augenbraue oder eine Kopfhaltung nehmen. Metin wollte danach "sie hält ihr Gesicht hin", umgesetzt ohne fremde Hand über Kopfneigung und gehobenes Kinn.

## Arm bleibt eingefroren (22.11.2026, Metin)

Bei Clips, die nur das Gesicht beschreiben, friert Kling den Körper ein, weil Start gleich Endbild ist und die Kamera festgenagelt wird. Eine einzige benannte Nebenbewegung reicht: "her left hand drifts up a little, her fingertips brush her hip, and by the last second it hangs relaxed at her side again exactly as in the first frame."

## Clips vom 22.11.2026, die auf Anhieb saßen

| Clip | Ziel | Einstellungen | Ergebnis |
|---|---|---|---|
| 6080 | kurz/freizeitgluecklich, ruhige süße Schleife, Wiegen, Blinzeln, kurz wegschauen | 4K, 10 s, Keyframes, Start gleich Endbild, 350 Credits | Schleife schließt mit Abstand 0,6, bester Wert aller gemessenen Schleifen; hinterher auf 0,75 gebremst (mci) |
| 26 (23.11.) | kurz/freizeitbegruessung, winken und Hand aufs Herz | 4K, 10 s, Keyframes | auf Anhieb gut, Originaltempo übernommen |
| 4144, 4128 | nacht/zeigenlang7 und zeigenlang9 | 4K, 30 s | ungeschnitten übernommen |
| 4198 | nacht/kuss, erster Kuss im Nachtoutfit | 4K, 30 s | ungeschnitten übernommen |

## Credits sparen (22.11.2026, Metin: "kann nicht haufen Credits für ein Clip")

Die Regel "vier Versuche pro Clip" gilt nicht mehr. Stattdessen Prompts nach dem Muster der Clips bauen, die auf Anhieb saßen (Eifersucht 3453, 3469, 3473; Rosen 3221, 3226; Schleife 6080): eine einzige klare Handlung, konkret beschrieben, feste Kamera, Start gleich Endbild, keine Kamerafahrt. Kamerafahrten und seltene Gesten sind die teuren Fehlschläge.

## Tempo im Prompt statt in der Nachbearbeitung (22.11.2026, Metins Idee)

"slowly" und "slow and smooth" liefern Zeitlupe, das stand schon im Log. Umgekehrt hilft es, das normale Tempo ausdrücklich zu verlangen: "at natural, real-time speed, as if filmed live, never slow motion". Diese Zeile gehört in jeden Prompt, in dem es nicht ausdrücklich langsam sein soll. Zum Prüfen gibt es seit 2.135.0 den Tempo Tester unter /tempo: zwei Clips nebeneinander mit Schieber, Metin nennt den Faktor.

## Takt haelt Kling nicht (gemessen 22./23.11.2026)

Alle 301 Clips wurden gemessen (`app/motion.py`, Add on 2.137.x). Ergebnis: kein Clip hat
einen Takt. Die Bewegungsmenge schwankt innerhalb eines Clips um das Zehnfache, nacht/tanz4
geht von fast still auf voll und zurueck, nacht/tanz37 wandert ueber 30 Sekunden hin und her.
librosa auf derselben Bewegungskurve findet ebenfalls nichts und liefert nur ihren
Standardwert von 120 bpm. Metins Eindruck war also richtig: "Kling ai macht komische clips
die zeitlich mal schnell mal langsam sind."

Folgen fuer die Prompts:
- Tempo in Worten ("at natural, real-time speed") hilft gegen Zeitlupe, erzeugt aber keinen
  gleichmaessigen Takt. Es bleibt drin, reicht aber nicht.
- Takt muss gezaehlt vorgegeben werden, nicht beschrieben: Anker ist Metins Musik mit
  100 bpm, also ein Schlag alle 0,60 s und 16 Schlaege in 9,6 s. Eine Bewegung pro zwei
  Schlaege heisst 8 Bewegungen im 10 s Clip.
- Nachtraeglich korrigierbar ist nur, was wir im Browser ohne Neu Rendern machen koennen:
  ein Tempo pro Clip (`r`) und eine Tempokurve fuer Stuecke im Clip (`k`), beides im Tempo
  Tester unter /tempo einstellbar.

## Profi Wissen Kling 4.0 (sechste Recherche, 23.11.2026, Metin: "Nur Profi Wissen, nichts selbst erfinden")

Gelesen wurden: die offizielle Kling 4.0 Anleitung (kling.ai/quickstart, vollständig), das offizielle API Handbuch und der offizielle Prompt Guide im Entwicklerbereich (dort stehen die Schreibregeln und die vollständigen Beispielprompts des Kling Teams), der offizielle Leitfaden zu Multiple Keyframes, die offizielle Motion Control Anleitung, die Anleitungen von fal.ai (API Anbieter, der Kling 4.0 produktiv betreibt) und acht GitHub Sammlungen. Jede Regel unten trägt ihre Herkunft: **[Kling]** = offizielle Kling Quelle, **[fal]** = fal.ai, **[Test]** = veröffentlichter Praxistest Dritter, **[GitHub]** = Community Handbuch, nur aufgenommen, wo es zu den offiziellen Aussagen passt. Was ich daraus für Leyla ableite, steht getrennt am Ende und ist als Ableitung gekennzeichnet.

### 1. Erst die Steuerart wählen, dann schreiben

Profis fragen zuerst, womit sich das Ergebnis steuern lässt, und erst danach, was im Text steht. **[fal]** nennt es so: jedes Eingangsmaterial bekommt genau eine Aufgabe.

| Was vorliegt | Steuerart | Was der Text dann leisten muss |
|---|---|---|
| ein Startbild | Bild zu Video | was nach genau diesem Bild passiert |
| Anfangs und Endzustand | erstes und letztes Bild | die Bewegung, die beide verbindet |
| mehrere Momente, die sitzen müssen | mehrere Keyframes | Reihenfolge, Übergänge, was gleich bleibt |
| Figur, Stil oder Bewegung als Vorlage | Omni Reference | was jede Vorlage steuert und was nicht |
| fertiges Video, das geändert werden soll | Video bearbeiten | was sich ändert und was bleibt |

Die App hat zwei Eingänge **[Kling]**: "Keyframes" (nur Bilder, bildgenaue Treue zu den Keyframes) und "Omni Reference" (Bilder, Videos, Elemente, Stimmen, bis 15 Vorlagen). Im Eingang Keyframes lassen sich keine Vorlagen hochladen. Omni Reference kann zusätzlich ein Bild als erstes Bild bekommen; das offizielle Beispiel schreibt sinngemäß: Bild 1 ist das erste Bild, Video 1 ist die Vorlage für Kamera, Bewegung, Timing und Schnitte.

### 2. Zeitpunkt einer Bewegung: Keyframes, nicht Worte

Das ist die wichtigste Stelle für unser Tempo Problem. **[Kling]** schreibt im API Handbuch unter Action and Expression: Wenn ein bestimmter Zeitpunkt nötig ist, bindet man ihn an Keyframes, Beispiel Hand heben in Sekunde 3, umdrehen in Sekunde 7. Ohne Keyframes entscheidet das Modell selbst über Reihenfolge und Zeitpunkt.

- Zeitangaben im Text ("0 bis 3 s: ...") sind Regieanweisung und keine bildgenaue Zusage **[fal]**. Deshalb kamen unsere Sekundenangaben nie genau.
- Bis zu 10 Keyframes, an beliebigen Stellen der Zeitachse. Offizielles Format für Zwischenbilder: pro Zeile der Zeitbereich und das zugehörige Bild, dann was an dieser Stelle passiert und wie die Kamera dorthin kommt, zum Beispiel `0–2.1s @Image1 ...`, `2.1–4.3s @Image2 ...` **[Kling]**.
- Ein Keyframe ist ein Moment, den der Zuschauer an dieser Stelle sehen muss. Wenn sich nichts Wichtiges ändert, kein weiteres Keyframe; zu viele machen die Abfolge schwerer zu steuern **[Kling]**.
- Vier Fehler, die Kling selbst nennt: zu viele Keyframes, zu viele Änderungen in einem Keyframe (Figur, Umgebung, Kamera, Licht zugleich), uneinheitliche Bilder, und ein Text, dessen Reihenfolge den Keyframes widerspricht. Erst die Zeitachse planen, dann den Text daran entlang schreiben **[Kling]**.
- Aufgabenteilung in einem Satz: Keyframes zeigen die wichtigen Momente, der Text erklärt den Weg dazwischen **[Kling]**.

### 3. Tempo, Takt und Choreografie: Referenzvideo, nicht Worte

Für Bewegung nach Vorgabe gibt es bei Kling zwei Werkzeuge, und beide nehmen ein Video als Vorlage.

**Omni Reference mit Bewegungsvideo (Kling 4.0)** **[Kling]**
- Ein Referenzvideo kann Darstellung, Bewegung, Kamera und Erzähltempo vorgeben. Auch Videos aus einem untexturierten 3D Rohmodell (White Model) und Tiefenkarten Videos werden angenommen, für genauere Kontrolle über Bewegung, Kamera und Timing.
- Offizielle Schreibweise für Bewegung: `Reference the fighting moves and attack timing in @Video1. Use @Image1 and @Image2 as the character design references.` Für die Kamera entsprechend Kamerapfad und Tempo von @Video1.
- Jede Vorlage braucht eine Rolle, und es muss dastehen, was nicht übernommen werden soll (Person, Kleidung, Hintergrund des Videos). Ohne Rolle rät das Modell.
- Bis 5 Videos, zusammen höchstens 30 s, jedes 3 bis 30 s.
- Kreatives Nachbauen: Tempo, Bildaufbau oder Präsentationsart eines Videos übernehmen und Figur oder Produkt austauschen. Kürzeste offizielle Form: `Replace the subject in @Video1 with @Image1. Keep everything else unchanged.` Je näher Vorlage und Ziel im Tempo und Aufbau liegen, desto besser.
- Ein Bewegungsvideo sichert das Aussehen nicht mit: Kling nennt für Videos Bewegung und Tempo als Aufgabe, nicht die Identität. Gesicht deshalb immer gegen das Bild prüfen **[fal]**.
- Abrechnung mit Videoeingang über die API: Eingangs und Ausgangssekunden zählen, mindestens das Doppelte der Ausgangslänge **[fal]**. In der App vor Generate den Preis am Knopf lesen.

**Motion Control (eigenes Werkzeug, Modell VIDEO 3.0)** **[Kling]**
- Überträgt Bewegung und Mimik aus einem Video auf die Figur im Bild. Für Kling 4.0 gibt es kein eigenes Motion Control **[GitHub, aus der offiziellen Modellliste]**; in Metins Konto steht es unter Tools (geprüft 23.11.2026).
- Vorlage: eine Person, ganzer Körper und Kopf sichtbar, ein durchgehender Take, keine Schnitte, keine Kamerabewegung, mäßiges Tempo, 3 bis 30 s. Zu schnelle oder komplexe Bewegung kann die Ausgabe kürzen, die Credits kommen dann nicht zurück.
- Bild im gleichen Ausschnitt wie das Video (Ganzkörper zu Ganzkörper), genug Platz um die Figur für große Bewegungen.
- Zwei Ausrichtungen **[Kling]**: der Vorlage folgen (Bewegung, Mimik, Kamera und Körperrichtung aus dem Video) oder dem Bild folgen (Richtung bleibt wie im Bild, Kamera über den Text). Für Tanz und Choreografie der Vorlage folgen, dann sind bis 30 s möglich, beim Bild folgen nur bis 10 s **[fal]**.
- Der Text beschreibt hier Umgebung, Licht und Stil, nicht die Bewegung; Bewegung im Text ist der häufigste Fehler **[fal]**.
- Gesichtstreue: "Bind Facial Element" unter dem Figurenbild, nutzt nur das Gesicht, Kleidung und Frisur kommen aus dem Bild.
- Kosten **[Kling]**: 12 Credits pro Sekunde Professional, 9 Standard. Ausgabe 720p oder 1080p, kein 4K **[GitHub, maciejdzierzek, Modellübersicht November 2026]**; das widerspricht unserer 4K Regel und spricht für den Weg über Omni Reference.

**Was Text allein bei Tanz leistet** **[Test]**: Ein Praxistest (ifeng, Oktober 2026, Tanz mit langen Ärmeln und Trommeln) bekam ein bestimmtes Choreografie Detail in Kling 4.0 auch nach sieben bis acht Runden nicht durchgehend hin, obwohl die Tester den Text immer genauer machten und die 15 Sekunden in Abschnitte zerlegten. Das deckt sich mit unserer Messung vom 22./23.11.: kein Clip hat einen Takt.

### 4. So schreibt das Kling Team selbst

Aus den vollständigen Beispielprompts im offiziellen Prompt Guide und den Schreibregeln im API Handbuch **[Kling]**:

- **Kurz anfangen.** Erst ein Satz mit Subjekt, Szene, Handlung und Gefühl. Danach nur ergänzen, was das Ergebnis wirklich ändert: Kamera, Timing, Ton, was erhalten bleiben muss. Länger ist nicht besser.
- **Sichtbares statt Wertungen.** Abstrakte Wörter (edel, filmisch, vintage) durch das ersetzen, was eine Kamera sieht: Lichtrichtung, Material, Farbe, Gegenstände. Zustand und Gefühl einer Figur über beobachtbare Handlungen beschreiben.
- **Positiv statt Verbote.** Verneinungen vermeiden, sie können Fehler vermehren. Wirklich nötig sind nur zwei, weil das Modell beides von selbst hinzufügen kann: keine Untertitel, keine Hintergrundmusik. Statt "Gesicht nicht zeigen" schreibt man "im Profil".
- **Feste Tatsachen statt Verbotslisten.** Die langen offiziellen Beispiele enden mit einem Block positiver Bedingungen in Tatsachenform (genau eine Figur, genau ein Gegenstand, das letzte Bild gleicht der Vorlage). Mengen werden zuerst festgenagelt.
- **Zählen statt umschreiben.** Bewegungen stehen mit Anzahl da: drei gezielte Hammerschläge, die Finger einmal krümmen, einmal blinzeln, ein kleiner Schwung nach vorn und zurück in die Ruhe.
- **Unterteilte Sekunden.** Innerhalb eines Abschnitts wird feiner gegliedert (zum Beispiel 0,0 bis 0,6 s greifen, 0,6 bis 1,5 s anheben, 1,5 bis 3,0 s wegtragen).
- **Ausdrückliches Halten am Ende.** Die Beispiele reservieren das Ende für Stillstand: die letzte halbe Sekunde vollkommen ruhig, die Kamera setzt sich auf das letzte Bild, der Gegenstand liegt regungslos in der Endposition.
- **Tempo als Eigenschaft der Bewegung.** Formulierungen aus den Beispielen: einzelne Handlungen behalten natürliches Gewicht und Tempo; die Kamera beschleunigt und bremst natürlich, ohne Schnitte und ohne Abspieltempo Effekte; natürliches Gehtempo und keine Zeitlupe; Tempo verringern vor dem Absetzen.
- **Physik eigens benennen.** Gewicht, Kontakt, Trägheit, wer was stützt, was sich nicht durchdringt.
- **Gliederung für große Aufnahmen.** Wiederkehrende Blöcke in den offiziellen Langbeispielen: Szene, aktive Vorlagen mit Rolle, Lageplan, erstes Bild und Stellung, Format, Optik, Kamera, Zeitablauf, Physik, Licht, Ton, Schauspiel, Stil, Qualität, positive Bedingungen. Das ist ein Muster, keine Pflicht.
- **Aufbau für Omni Reference:** Rollen der Vorlagen, Gesamteinstellung (Szene, Stil, Kameraton), Ablauf in Zeitabschnitten, Ton.
- **Offizielle Formel aus der Ankündigung:** Subjekt, Handlung, Ort, Kamera, Licht, Tempo, Ton.
- **Eine Hauptbewegung der Kamera pro Einstellung**, und nie zwei, die sich widersprechen (fest und gleichzeitig Umkreisen) **[fal]**.
- **Wenn das Ergebnis nicht passt** **[Kling]**: zuerst prüfen, ob jede Vorlage eine Rolle hat, dann abstrakte Wörter ersetzen, dann die @ Verweise kontrollieren.

### 5. Start und Endbild wie in einer Produktion

- **[fal]** Endbild zuerst erzeugen und das Startbild daraus ableiten (gleiche Kameraposition, nur der Zustand ändert sich), damit alles andere identisch bleibt. Im Text landet der Clip für die letzten zwei Sekunden auf dem Bildaufbau des Endbilds.
- **[Kling]** Erstes Bild: beschreiben, was danach passiert. Letztes Bild: beschreiben, was davor passiert. Beide zusammen legen Anfang und Ende fest.
- **[Kling]** Was sich gegenüber dem Bild stark unterscheidet, kann einen Schnitt auslösen; Bewegungen wählen, die zum Bild passen. Komplexe Physik (springender Ball, Wurfbahn) gelingt schlecht.
- **[GitHub, Yuyyxz, passt zur offiziellen Logik von Zustand A nach B]** Das Modell rechnet von Zustand zu Zustand. Ein Startbild soll Spannung haben, aber noch keinen Höhepunkt zeigen. Pro Abschnitt eine Hauptänderung und höchstens eine Nebenänderung. Sind Start und Endbild fast gleich, fehlt dem Modell das Ziel, und es bewegt sich beliebig; dann braucht es Zwischenbilder oder eine Bewegungsvorlage.
- **[GitHub, flaqai]** Die letzten ein bis zwei Sekunden für Abbremsen und ein brauchbares Endbild einplanen.
- **Schleifen:** Die offiziellen Kling Quellen sagen dazu nichts. Belegt ist nur die Praxis gleiches Bild als Start und Ende plus kurze Überblendung von 0,3 bis 0,5 s **[GitHub, maciejdzierzek]**.

### 6. Arbeitsweise

- **[fal]** Gegen einen sichtbaren Fehler arbeiten und pro Versuch nur eine Sache ändern; Prompt, Vorlagen, Reihenfolge und Einstellungen zusammen aufheben.
- **[fal]** Wirkt eine Szene gehetzt: ein Ereignis streichen, statt einen Absatz hinzuzufügen. Läuft das Tempo weg: die Zeitachse vereinfachen.
- **[Kling]** Die ganze Abfolge prüfen, nicht Einzelbilder, und nur den Teil nachbessern, der es braucht.
- **[fal, Kling]** Profis testen Bewegung billig (720p oder Flash) und rendern erst dann final. Flash kann aber kein letztes Bild und keine mehreren Keyframes. Metins Regel bleibt: bei uns direkt 4K, weil wir Start und Endbild brauchen.
- Kling 4.0 gibt 24 Bilder pro Sekunde aus (API Doku laut **[GitHub, maciejdzierzek]**, von uns an den eigenen Dateien gemessen). Über die offizielle Schnittstelle erzeugte Dateien werden 30 Tage aufbewahrt **[Kling]**, also zeitnah sichern.
- **[GitHub, Yuyyxz, als Beobachtung gekennzeichnet, deckt sich mit Kling]** Vorlagen wiegen dort, wo sie sich mit dem Text überschneiden, schwerer als der Text; der Text soll nur tragen, was ein Bild nicht kann: Zeit, Kamera, Ton, Bedingungen. Ein verneintes Wort ruft seinen Begriff trotzdem auf (unsere Brille vom 22.11.). Fehler wachsen mit der Cliplänge. Was klein im Bild ist (Gesicht in der Totalen, Hände), verliert zuerst Details.

### 7. Was sich an unseren bisherigen Regeln ändert

| Bisher im Dokument | Stand nach dieser Recherche |
|---|---|
| Musikrichtung im Prompt bestimmt den Rhythmus | Nicht belegt und von unserer Messung widerlegt. Rhythmus kommt aus einem Referenzvideo, Zeitpunkte aus Keyframes. |
| Tempo Zeile "never slow motion" in jeden Prompt | Bleibt als Schutz vor Zeitlupe, aber positiv formuliert wie in den offiziellen Beispielen (natürliches Gewicht und Tempo jeder Handlung). Einen Takt erzeugt sie nicht. |
| Sekundenangaben steuern den Ablauf | Sie sind Regie, keine Zusage. Was sitzen muss, bekommt ein Keyframe. |
| Alte Clips 1:1 nachbauen über genauere Beschreibungen (sieben Versuche, rund 2.450 Credits) | Der offizielle Weg ist der alte Clip als Bewegungsvorlage. |
| Vier Versuche pro Clip einplanen | Bleibt abgeschafft. Stattdessen pro Versuch genau eine Änderung gegen einen benannten Fehler. |

### 8. Ableitung für Leyla (meine Anwendung der Quellen, noch nicht getestet)

1. **Alte Lieblingsclips in 4K neu, ohne die Bewegung neu zu erfinden.** Alter Clip als @Video1, das 4K Outfitbild als @Image1, Rolle: Bewegung und Timing aus dem Video, Aussehen aus dem Bild, nichts sonst aus dem Video übernehmen. Das ist genau der Fall Action Reference beziehungsweise Kreatives Nachbauen. Betrifft die 217 alten Clips und den Nachbau von tanz8 und tanz9.
2. **Ein Takt für alle Tänze.** Eine einzige Tanzvorlage im gewünschten Tempo (Metins Musik liegt bei 100 bpm) als Bewegungsvideo für alle Tanzclips einer Gruppe. Dann stammt der Takt aus derselben Quelle.
3. **Das Skalpell.** Wenn eine Stelle im Clip zu einer bestimmten Sekunde sitzen muss, ein Zwischenbild für diese Sekunde setzen, statt hinterher Tempo zu verbiegen. Zwischenbilder lassen sich aus guten Clips ziehen (Extract Frames).
4. **Beim ersten gemeinsamen Test zu prüfen, bevor Credits fließen:** ob Omni Reference in Metins Konto 4K anbietet, was ein Clip mit Videovorlage laut Generate Knopf kostet, und ob das erste Bild im Eingang Omni Reference so bildgenau sitzt wie im Eingang Keyframes (wichtig für unsere Übergänge).

Quellen sechste Recherche: kling.ai/quickstart/kling-4-model-user-guide; kling.ai/document-api/api/usage-guide/kling-4-0 (Abschnitte 2.2, 6.2, 6.5, 6.9, 8, 10); kling.ai/document-api/api/usage-guide/kling-4-0-prompt-guide (Abschnitte 2, 3, 9); kling.ai/blog/kling-4-multiple-keyframes-guide; kling.ai/blog/kling-4-ai-video-model; kling.ai/quickstart/motion-control-user-guide; kling.ai/quickstart/image-to-video-guide; fal.ai/learn/devs/kling-4-prompting-guide; fal.ai/learn/tools/how-to-use-kling-4-0; fal.ai/learn/devs/kling-video-2-6-motion-control-prompt-guide; tech.ifeng.com/c/8xVjyJ3rBgP (Tanztest); chatcut.io/blog/kling-4-0-review. GitHub, vollständig gelesen: Yuyyxz/kling-prompt-engineering (Kapitel 07, 14, 15, 23), maciejdzierzek/kling-ai-prompt-generator (Stand November 2026, mit Quellenliste), kingvid-ai/kling-4-prompt-skill, flaqai/awesome-kling-4-0 (Prompt Guide und Rezepte), DSeaStar/awesome-kling, aedev-tools/kling-3-prompting-skill; BravoNeo/awesome-kling-4-0-prompts und kingvid-ai/awesome-kling-4-prompts sind reine Promptsammlungen ohne Regeln und wurden nur gesichtet.

## Erster Clip nach Profi Art: schwarz/freizeitgluecklich neu (23.11.2026, gestartet 12:43)

Metin wollte die alte 1176 x 1764 Schleife im langen Freizeitkleid in 4K ersetzen: "ruhig aber beweglich", damit sie nicht mit einem Berührungsclip verwechselt wird (keine einzelne Reaktion wie Wegschauen oder Auflachen). Aus drei Varianten wählte er "Wiegen im Stand".

Einstellungen: Kling 4.0, Eingang Keyframes, Start und Endbild dasselbe Favoritenbild (Leyla allein im langen schwarz goldenen Kleid, von Metin selbst gesetzt, von Claude groß geprüft), 4K, 10 s, Adaptive, 1 Ausgabe, 350 Credits.

Prompt: "Use the first keyframe as the first frame and the last keyframe as the last frame. A single continuous shot with no cuts. The camera stays perfectly still on a tripod and keeps the full body framing of the keyframes; the background and the reflections on the floor stay exactly as they are. Exactly one woman; both of her feet stay planted on the same spot the whole time. She stands at her place and sways gently and continuously. Her eyes stay on the lens with a calm, warm smile and she blinks naturally. Every movement keeps natural weight and real-time speed. 0 to 1 seconds: she breathes in softly and her shoulders rise a little. 1 to 3 seconds: she shifts her weight slowly from her standing leg onto her other leg; her hips swing out to that side, her upper body follows with a slight lean, and her hair and the hem of her dress sway after the movement. 3 to 5 seconds: she shifts her weight smoothly back onto the first leg; her hips swing across, her arms hang loose and move along, her fingertips brush her dress. 5 to 7 seconds: she shifts her weight onto the other leg once more in the same calm rhythm. 7 to 9 seconds: she shifts back and returns to the stance of the first frame while her hair settles. 9 to 10 seconds: she holds exactly the pose of the last frame, completely still. No subtitles, no background music."

Herkunft der Teile (Metin fragte vor dem Klick: "hast du alle Profi Regel beachtet und nicht selbst dazu erfunden?"):
- Aus den Profi Quellen: ein durchgehender Take, Kamera positiv beschrieben, Menge und Stand als feste Tatsache, Ablauf in Zeitabschnitten, gezählte Gewichtswechsel, natürliches Gewicht und Tempo, ausdrücklicher Stillstand am Ende, nur die beiden offiziell nötigen Verbote.
- Aus unserem eigenen Log, nicht aus Profi Quellen: die Fingerspitzen am Kleid (gegen den eingefrorenen Arm, 22.11.) und der erste Satz mit "first keyframe" statt der offiziellen Schreibweise mit @Image1 und @Image2.
- Vor dem Klick gestrichen: der Vergleich "like someone waiting happily", weil er kein sichtbares Geschehen beschreibt und damit gegen die offizielle Regel verstößt.
- Nicht anwendbar: feste Zeitpunkte über Zwischenbilder, weil es für das Wiegen keine gibt. Der gleichmäßige Rhythmus hängt deshalb weiter am Text, und Zeitangaben im Text sind laut fal.ai keine bildgenaue Zusage.

Metins Vorgabe für das Ergebnis: Der Clip kommt unverändert als 4K Original in die App, ohne Schnitt und ohne Tempoänderung ("Wenn wir das wie Profis gemacht haben, brauchen wir keine Tempo Änderung"). Dieser Clip ist damit der Test, ob die Profi Schreibweise trägt. Ergebnis hier nachtragen.

Bedienung (23.11.2026): Bei schmalem Browserfenster liegt der Einstellungsknopf "4K · 10s · Adaptive · 1" verdeckt unter dem Generate Knopf; die Knopfzeile lässt sich mit dem Mausrad seitlich schieben. Die Länge steht nach dem Öffnen einer neuen Aufgabe wieder auf 5 s (175 Credits) und muss im Feld auf 10 gestellt werden. Metin sieht mit, wenn der Tab im Vordergrund ist, und setzt die Bilder gern selbst; Claude prüft sie danach groß.

Ergebnis (Clip 5030, 23.11.2026 12:48, Metin: "tempo ist falsch"): 2352 x 3524, 24 Bilder pro Sekunde, 10,04 s. Inhaltlich richtig: sie wiegt sich nach beiden Seiten, Arme gehen mit, Füße bleiben stehen, Blick bleibt in der Kamera, Schleife schließt gut (Abstand Anfang zu Ende 0,54). Aber deutlich zu langsam: Bewegungsmenge im Mittel 0,94 (Tänze liegen bei 2 bis 4), ein Schwung nach einer Seite dauert rund 2,5 s, bei Sekunde 5 steht sie fast still (0,25).

Ursache liegt im Prompt, nicht bei Kling: Kling hat den Zeitplan weitgehend befolgt (Spitzen bei 2,5 s und 6 s), aber der Plan selbst war Zeitlupe. Zwei Fehler von Claude:
1. Zu wenig Bewegung für 10 s: nur vier Gewichtswechsel, je zwei Sekunden lang. Ein natürliches Wiegen im Stand ist etwa doppelt so schnell.
2. Bremswörter in fast jedem Satz ("gently", "slowly", "softly", "smoothly", "calm rhythm"), obwohl unser eigenes Log vom 21.11. genau davor warnt. Die Zeile "natural weight and real-time speed" kommt gegen diese Häufung nicht an.

Lehre: Das Tempo steckt in der Anzahl der Bewegungen pro Sekunde und in den Verben, nicht in einer Tempo Zeile. Für ein ruhiges, aber lebendiges Wiegen etwa einen Gewichtswechsel pro Sekunde zählen und kein einziges Bremswort schreiben; "ruhig" entsteht durch kleine Ausschläge, nicht durch langsame Ausführung.
