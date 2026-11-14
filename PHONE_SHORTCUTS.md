# Phone home screen buttons

Both buttons use the Home Assistant Companion app widget "Button" (German: Schaltfläche). Samsung does not frame widgets, so the icon appears large and without a Chrome badge.

## Mini PC AUS
Script `script.mini_pc_herunterfahren` (shuts down the HAOS host, asks for confirmation). Widget: Button, pick the script, pick the icon.

## Leyla memory page
Script `script.leyla_gedaechtnis` (alias "Leyla Gedächtnis öffnen", icon mdi:brain) sends `notify.mobile_app_metins_handy` with `message: command_activity`, `title: android.intent.action.VIEW`, `data.intent_uri: http://192.168.2.240:8082/` and `intent_package_name: com.android.chrome`. This opens the page in Chrome. Widget: long press the home screen, Widgets, Home Assistant, Button, pick the script.
Created 14 Nov 2026 through the HA config API. Whether the page opens full screen (installed web app) or as a browser tab is still to be tested.
