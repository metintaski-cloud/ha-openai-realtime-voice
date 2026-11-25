# Weckwort "Hallo Leyla": wie es wirklich funktioniert und wie Fehlwecker weggehen

Recherche vom 24.11.2026, 12:50, nachdem Metin sagte: "Vielleicht sollst du dich erstmal im Internet extrem stark recherchieren und herausfinden, wie das wirklich funktioniert." Vorher hatte ich an diesem Tag einen Umweg gebaut (Prüfung auf dem Server per Spracherkennung), der das Problem nicht löst. Dieses Dokument ist der Stand, an den sich jede weitere Arbeit am Weckwort hält. Erst lesen, dann bauen.

## Was bei uns läuft

- Das Weckwort erkennt ein kleines Modell auf dem Gerät selbst (microWakeWord, Datei `hallo_leyla.tflite` im Repo, Manifest `hallo_leyla.json`, Version 2, trainiert am 2.11.2026 von Metin mit Opus).
- Trainiert mit dem Trainer von TaterTotterson (`ghcr.io/tatertotterson/microwakeword`, Docker mit Grafikkarte auf Metins PC, Start über `Hallo Leyla Trainer starten.bat` auf dem Desktop, Daten in `C:\mww`, Oberfläche auf Port 8789). In `C:\mww` gibt es die Ordner `personal_samples`, `negative_samples`, `captured_audio`, `trained_wake_words`, `output`, `work`. Was darin liegt, steht im nächsten Abschnitt.
- Live Einstellung am Gerät: Schwelle 99 Prozent, Fenster 6, `gain_factor: 4`.
- Messwerte: rund 5 Fehlstarts am Tag, 29 von 31 bei laufendem Fernseher (türkisches Fernsehen). Gleichzeitig muss Metin oft 2 bis 3 Mal rufen.

- Beobachtung 24.11.2026, 22:25 (Metin): seine Mutter konnte Leyla mit "Hallo Leyla" nicht wecken, obwohl ihre Stimme im Training war. Passt zu den Messwerten (Schwelle 99 Prozent, er selbst muss oft 2 bis 3 Mal rufen). Zu prüfen: hat der leise Sammler (Schwelle 0,70) ihre Rufe aufgenommen? Dann hört das Modell sie, nur unter 99 Prozent.
- Zählung 24.11.2026, 22:28 (`/api/wakestats`): heute 37 Mal geweckt, davon 12 Fehlstarts; Sammler seit dem Mittag: 50 Beinahe Treffer, 39 sauber (`n0_f0`), 11 zu prüfen. Die Zählung nennt keine Uhrzeiten, welche Clips von der Mutter stammen, zeigt sie nicht; ihre vergeblichen Rufe mit Metins zwei erfolgreichen Rufen kurz danach passen aber genau auf das Muster "prüfen" (noch ein Treffer oder ein Wecken binnen 15 Sekunden). Metin rief danach zweimal, beide Male reagierte sie: Gerät und Modell arbeiten, es ist die Trefferquote. Idee für später: eine Liste der Beinahe Clips mit Uhrzeit in der App, damit man solche Fälle zuordnen kann.
- VERDACHT AUF DIE GERÄTE SOFTWARE VOM 24.11.2026 (Metin, 22:33: "ich hatte es schon lange auf 99 Prozent und Leyla hatte darauf reagiert, sonst hätte ich das früher angegangen"; 22:34: der Fernseher war aus). Am Gerät hat sich nur am 24.11. etwas geändert: 11:48 Vorlauf 2500 ms, 12:29 Vorlauf 4000 ms mit `note_wake`, 13:36 der leise Sammler (das Modell läuft ein zweites Mal mit Schwelle 0,70) und der Vorlauf von Kanal 1 mit Faktor 4. Möglich, dass der zweite Modelllauf oder der Vorlauf Puffer die Erkennung des Hauptmodells schwächt (Rechenzeit auf dem ESP32). Nicht bewiesen. Messplan, ein Schritt nach dem anderen: (1) Fernseher aus, Metin zehn Rufe, Mutter zehn Rufe, Treffer zählen; (2) bei schlechter Quote mit Metins Ok den Sammler vom Gerät nehmen und genauso zählen; (3) wenn das nicht hilft, auch den Vorlauf abschalten und zählen. Erst danach entscheiden, wie die Gegenbeispiele gesammelt werden.
- Präzisierung (Metin, 24.11.2026, 22:35): bei ihm reagiert Leyla, nur bei seiner Mutter nicht. Lesart: seine Stimme kommt mit Abstand über 99 Prozent, ihre liegt näher an der Schwelle, eine kleine Schwächung trifft sie zuerst. Schritt 1 darum nur mit der Mutter: zehn Rufe am gewohnten Platz, Fernseher aus; Metin nennt die Treffer, Claude liest davor und danach den Zähler des Sammlers (Stand 22:28: 50 gesammelt, 39 sauber, 11 prüfen), der Zuwachs zeigt, wie viele ihrer Rufe über 0,70 kamen, aber unter 0,99 blieben.

## Was im Trainer liegt (angesehen am 24.11.2026, 12:58, `C:\mww`)

- `personal_samples`: 121 echte Rufe (laut Metin, 24.11.2026, 22:26, sind auch Rufe seiner Mutter darunter: "Sie wurde auch damit trainiert"; wie viele von wem, war nicht notiert; Messung der Stimmhöhe am 24.11.2026, 22:31, ohne Anhören: zwei klar getrennte Gruppen in der Reihenfolge der Dateien, `wohnzimmer_001` bis `050` mit mittlerer Tonhöhe um 170 bis 200 Hz und `wohnzimmer_051` bis `121` um 230 bis 250 Hz, also vermutlich rund 50 Rufe der tieferen und rund 71 der höheren Stimme; alle 121 liegen in `personal_samples` und wurden am 2.11.2026 um 14:12 zusammen hochgeladen), `wohnzimmer_001.wav` bis `wohnzimmer_121.wav`, 16 kHz mono, 1,2 bis 2,9 s, Pegel rms 495 bis 3756 (Mitte 1365), nichts übersteuert; hochgeladen am 2.11.2026 als `hallo_leyla_wohnzimmer.zip`. Sie wurden im Training benutzt (Gewicht 3,0).
- `negative_samples`: LEER. Im Trainingsprotokoll steht wörtlich "No WAVs found for reviewed negatives in: /data/negative_samples (skipping)" und "continuing with stock negatives". Echte Fehlwecker aus dem Wohnzimmer hat das Modell also nie gesehen. Dazu kamen 2040 künstlich erzeugte ähnlich klingende Sätze als Gegenbeispiele.
- Training: 50 000 künstliche Rufe, 80 000 Schritte, sechs Läufe am 2.11.2026, der letzte um 15:07 bis 16:34.
- Urteil des Trainers selbst über das Modell, das heute läuft: "Needs attention", erkannte Rufe 87,6 Prozent, Fehlwecker 0,21 pro Stunde bei Schwelle 0,99 und Fenster 5 (gemessen auf den Testdaten des Trainers, 9,67 Stunden Umgebungston). 0,21 pro Stunde sind rund 5 am Tag: das ist ziemlich genau, was wir zählen. Bei Schwelle 0,94 wären es laut Protokoll 6,5 Prozent überhörte Rufe und 0,375 Fehlwecker pro Stunde.
- Folgerung: Metins Gefühl stimmt mit den Zahlen überein (er muss mehrfach rufen, und sie weckt trotzdem falsch). Was fehlt, sind allein die echten Gegenbeispiele.

## Wie die Erkennung arbeitet

- Das Modell gibt alle 10 ms eine Wahrscheinlichkeit aus. Geweckt wird, wenn der Mittelwert über das Fenster über der Schwelle liegt (ESPHome `micro_wake_word`: `probability_cutoff`, `sliding_window_size`).
- Höhere Schwelle heißt weniger Fehlwecker und mehr überhörte Rufe, niedrigere umgekehrt. Die Schwelle verschiebt nur den Arbeitspunkt, sie bringt dem Modell nichts bei. Genau das sehen wir: 99 Prozent, trotzdem Fehlwecker, und er muss mehrfach rufen.
- Das eingebaute VAD Modell von `micro_wake_word` blockt nur Geräusche ohne Stimme. Fernsehen ist Stimme, es hilft hier nicht.
- Auf der Voice PE hört das Weckwort Modell Kanal 1 des XMOS Chips (Stufe Rauschminderung, ohne automatische Verstärkung) mit `gain_factor: 4`. Kanal 0 hat die automatische Verstärkung und ist für die Spracherkennung gedacht.

## Warum ein eigenes Modell falsch weckt

- Trainiert wird mit künstlichen Stimmen (TTS) für den Ruf und mit fertigen Geräusch und Sprach Sammlungen als Gegenbeispiele. Das Modell hat nie gehört, was in DIESEM Raum durch DIESES Mikrofon kommt, hier türkisches Fernsehen.
- Zu leichte Gegenbeispiele: ein Modell besteht die Prüfung im Trainer und springt zu Hause trotzdem auf ähnlich klingende Sprache an.
- Künstliche Stimmen decken Aussprache, Abstand und Mikrofon der echten Leute nicht ab, darum werden echte Rufe überhört.

## Was nachweislich hilft

1. Echte Fehlwecker als harte Gegenbeispiele ins Training geben: den Ton aufnehmen, der fälschlich geweckt hat, als Gegenbeispiel einsortieren, neu trainieren, neu messen. Ein dokumentiertes Projekt: 208 echte Fehlwecker Clips aus dem Alltag, danach Fehlwecker auf der schweren Testmenge 1 von 140 statt 91 von 140; erkannte echte Rufe 47 von 50 statt 50 von 50. Danach wurde dort die Schwelle von 0,97 auf 0,9 gesenkt und brachte 5 Rufe zurück, ohne messbar mehr Fehlwecker.
2. Echte Rufe der Leute, die sie benutzen, durch das echte Gerät im echten Raum. Ein Trainer gibt echten Clips eigenes Gewicht (3 Kopien, Gewicht 2,0) und echten Fehlweckern Gewicht 1,5 mit dreifacher Strafe.
3. Messen statt glauben: Clips zurückhalten, die das Training nie gesehen hat, am besten ganze Tage, und darauf erkannte Rufe und Fehlwecker zählen. Die Schwelle erst danach wählen.
4. Unser Trainer kann das: Ordner `negative_samples` (geprüfte Fehlwecker, werden als eigener Satz harter Gegenbeispiele ins Training genommen), `personal_samples` (echte Rufe), Hochladen von WAV über den Reiter Samples, und er wählt Schwelle (0,95 bis 1,00) und Fenster (5, 6, 7) selbst nach erkannten Rufen und Fehlweckern pro Stunde.

## Was das für uns heißt

- Der Vorlauf, den das Gerät seit heute schickt, ist das richtige Werkzeug zum SAMMELN, nicht zum Prüfen. Der Vorlauf eines Fehlweckers ist genau der Ton, der sie geweckt hat, mit der Stelle des Weckworts (`wake_ms`).
- FEHLER IM HEUTIGEN STAND: der Vorlauf nimmt Kanal 0 (mit automatischer Verstärkung). Das Modell hört Kanal 1 mit Faktor 4. Für das Training muss der Vorlauf denselben Ton enthalten wie das Modell. Vor dem Sammeln umstellen, sonst passen die Beispiele nicht zum Gerät.
- Die 69 alten Aufnahmen sind der Ton NACH dem Wecken (24 kHz, Kanal 0): als allgemeine Fernseh Gegenbeispiele brauchbar, aber nicht der Auslöser.
- Menge: bei 5 Fehlweckern am Tag dauern 200 Clips rund 40 Tage. Schneller geht es mit einem zweiten, leisen Durchlauf desselben Modells mit niedriger Schwelle, der nichts auslöst und nur Clips sammelt (Beinahe Treffer vom Fernseher, und Rufe, die bei 99 Prozent überhört wurden). Das ist ein Vorschlag, noch nicht gebaut.
- Fernsehen von echtem Ruf unterscheiden kann bei den gesammelten Clips sicher nur ein Mensch. Regel bei uns: endete das Wecken ohne Gespräch, ist es ein Gegenbeispiel; wurde es ein echtes Gespräch, ist es ein Ruf. Zweifelsfälle hört Metin im Trainer an (Reiter Captured Audio: "This is good" oder "False wake").
- Die Prüfung per Spracherkennung auf dem Server bleibt nur als Zähler im Protokoll. Abweisen und stilles Zuhören sind verworfen (STATUS.md, 24.11.2026).

## Der leise Sammler (gebaut am 24.11.2026 mit Metins Ja von 12:57, Server 2.158.0)

- Auf dem Gerät läuft das Modell ein zweites Mal mit Schwelle 0,70 (`hallo_leyla_sammler.json`, Weckwort "Leyla Sammler"). Spricht es an, startet nichts; das Gerät schickt nur die letzten 4 Sekunden des Mikrofons an den Server (Kanal 1 mit Faktor 4, also genau der Ton, den das Modell hört).
- Der Server legt jeden Clip 15 Sekunden später in `/data/near_wakes` ab: `beinahe_<Tag>_<Zeit>_n0_f0.wav`. Verworfen wird er, wenn innerhalb von 3 Sekunden ein Gespräch per Weckwort begann (dessen Vorlauf ist derselbe Ton). `f1`: innerhalb von 15 Sekunden kam noch ein Beinahe Treffer oder ein Wecken (jemand hat vielleicht noch einmal gerufen). `n1`: eine Spracherkennung mit ihrem Namen als Stichwort hat ihren Namen gehört.
- Ins Training dürfen ungehört nur `n0_f0`. Alles andere muss sich ein Mensch anhören, denn ein echter Ruf als Gegenbeispiel würde dem Modell beibringen, ihren Namen zu überhören.
- Zählen: `GET http://192.168.2.240:8082/api/wakestats`, Feld `beinahe` (gesammelt, sauber, prüfen, pro Tag).
- Die Vorläufe echter Fehlwecker (`/data/false_wakes/..._vorher_w<ms>.wav`) kommen seit derselben Umstellung auch vom richtigen Kanal; die vom 24.11. vor der Umstellung (Kanal 0) nicht mitnehmen.

**Zählung vom 25.11.2026, 13:20** (`GET /api/wakestats`, knapp 24 Stunden nach dem Start des Sammlers am 24.11. um 13:36): 132 Clips gesammelt, davon 101 sauber (`n0_f0`) und 31 zu prüfen, keiner abgelehnt, keiner durch ein Gespräch ersetzt. Je Tag: 24.11. (ab 13:36) 39 sauber und 11 zu prüfen, 25.11. (bis 13:20) 62 sauber und 20 zu prüfen. Das sind rund 100 saubere Clips am Tag, also weit über den erhofften 30: die Schwelle des Sammlers (70 Prozent) bleibt, wie sie ist. Die Marke von rund 200 sauberen Clips ist nach dieser Rate am 26.11. gegen 13 bis 14 Uhr erreicht. Fehlstarts der Woche (geweckt / davon Fehlstart): 19.11. 3 / 0, 20.11. 12 / 3, 21.11. 8 / 2, 22.11. 15 / 3, 23.11. 6 / 4, 24.11. 37 / 12, 25.11. bis mittags 4 / 4.

## Plan (mit Metin abzustimmen, immer ein Schritt)

1. In `C:\mww` nachsehen, was schon da ist: wie viele echte Rufe, wie viele Gegenbeispiele, mit welcher Trainer Version das Modell vom 2.11. entstand.
2. Vorlauf auf den Ton umstellen, den das Modell hört (Kanal 1, Faktor 4), dann sammeln: Fehlwecker und echte Rufe getrennt, auf dem Server.
3. Altes Modell auf den gesammelten Clips messen (erkannte Rufe, Fehlwecker), damit es eine Zahl gibt, gegen die das neue antritt.
4. Neu trainieren mit den Gegenbeispielen und den echten Rufen, auf zurückgehaltenen Clips messen, alt gegen neu.
5. Nur wenn das neue Modell besser ist: aufs Gerät, Schwelle nach den Messwerten wählen, eine Woche zählen.

## Quellen

- ESPHome, Micro Wake Word: https://esphome.io/components/micro_wake_word/
- TaterTotterson, microWakeWord Trainer (Nvidia Docker): https://github.com/TaterTotterson/microWakeWord-Trainer-Nvidia-Docker
- TaterTotterson, openWakeWord Trainer (gleiche Ordner und Hochlade Schnittstelle beschrieben): https://github.com/TaterTotterson/openWakeWord-Trainer
- interkelstar, microwakeword-trainer (208 Fehlwecker Clips, 91/140 auf 1/140): https://github.com/interkelstar/microwakeword-trainer
- wakesmith (Gewichte für echte Clips, Messen an zurückgehaltenen Tagen): https://github.com/vithurshanselvarajah/wakesmith
- Voicute, warum eigene Modelle falsch wecken: https://www.voicute.com/articles/microwakeword-custom-models-false-positives.html
- microWakeWord Dokumentation (Auswahl der Gewichte nach Fehlweckern pro Stunde): https://docsearch.algolia.com/mcp/docs/repo/ohf-voice/micro-wake-word
- Voice PE, Kanäle des XMOS Chips (Kanal 0 AGC, Kanal 1 NS; Weckwort auf Kanal 1 mit gain_factor 4): https://community.home-assistant.io/t/help-needed-xmos-xu316-aec-not-working-on-voice-preview-edition-vpe/975285 und https://community.home-assistant.io/t/home-assistant-voice-pe-custom-wake-words-please/845139?page=6
