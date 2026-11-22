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
