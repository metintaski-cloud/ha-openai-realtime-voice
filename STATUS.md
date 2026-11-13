# Leyla: Stand, Entscheidungen, offene Punkte

Diese Datei ist das Gedaechtnis des Projekts. Wer eine Sitzung beginnt, liest sie zuerst. Wer etwas entscheidet oder abschliesst, traegt es hier ein (Stand: 13 Nov 2026). README, CHANGELOG, Vorlage voice_pe_config.yaml und die Notizen im Client Ordner wurden am 13 Nov 2026 auf den echten Stand gebracht.

## Feste Entscheidungen
- Leyla behaelt ihre Stimme, kein Stimmenwechsel. Die Stimme "Brise" gibt es nicht auf dem Speech Endpoint, deshalb Ansagen ueber GPT Live mit gespeicherten Clips (merken: true).
- Wake Word: nur "Hallo Leyla" (Modell hallo_leyla), Nabu und Mycroft sind entfernt. probability_cutoff 99 Prozent, gain_factor bleibt 4 (Mama soll weiter erkannt werden).
- Fernseher wird vor Ansagen leiser gestellt (before_play/after_play).
- Antwortstil fuer Metin: kurz, hoechstens 3 Saetze, keine Gedankenstriche, Anleitungen Schritt fuer Schritt mit "weiter".
- Code immer aufraeumen und Metin ueber Struktur und Dateigroesse informieren.

## Regel gegen veraltete Infos
- Jede Aenderung an Server, Geraet oder Entscheidungen wird noch in derselben Sitzung in STATUS.md, DEPLOYED.md und der passenden AGENTS.md nachgezogen und committed.
- Werte aus diesen Dateien vor der Nutzung gegen das echte System pruefen (Add on Version, Live Config), Datum der letzten Pruefung steht in DEPLOYED.md.

## Umgebung
- HAOS 192.168.2.240, Voice PE ha-voice-openai 192.168.2.241, Add on Slug 5b94124a_openai_realtime_voice, ESPHome Add on 5c53de3b_esphome.
- Deploy Ablauf Server: Tests, Version in config.yaml erhoehen, commit, push, Store neu laden, ohne aktive Sitzung Update ausloesen. Details in openai_realtime_voice/AGENTS.md.
- Geraete Config aendern: siehe home-assistant-voice-pe/AGENTS.md (Abschnitt Browser Route).

## Version und Zustand
- Server 2.52.7, 183 Tests gruen, main.py ca. 1400 Zeilen, technik.py ca. 570 Zeilen.
- Wake Word Cutoff 99 Prozent wurde am 13 Nov 2026 per Netzwerk installiert, Ergebnis noch zu pruefen.

## Offen
- Pruefen, ob Fehlaktivierungen seltener werden und Mamas "Hallo Leyla" noch erkannt wird.
- Mikrofonpegel von Mamas echter Sitzung ansehen (Log "Mic level (2 s)").
- Weiteres Aufraeumen: lange Funktionen in main.py, technik.py.
- Dreame Sperrzone Anleitung (wartet auf "weiter").
- Fehlaktivierungen: Modell mit gesammelten Samples nachtrainieren.
- Externes Backup einrichten.
