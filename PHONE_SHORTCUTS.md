# Phone home screen buttons

Both buttons use the Home Assistant Companion app widget "Button" (German: Schaltfläche). Samsung does not frame widgets, so the icon appears large and without a Chrome badge.

## Mini PC AUS
Script `script.mini_pc_herunterfahren` (shuts down the HAOS host, asks for confirmation). Widget: Button, pick the script, pick the icon.

## Leyla memory page: dropped
Tried a script button (notify command_activity opening http://192.168.2.240:8082/). The widget only offers Home Assistant (mdi) symbols, not our own icon, so Metin decided on 14 Nov 2026 to leave it out. The script was deleted again. The memory page stays a Chrome installed app.
