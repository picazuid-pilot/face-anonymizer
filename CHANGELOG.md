# Changelog

## 2.0.0

### Opgelost
- **Debug-kaders en ID-labels kwamen in de livestream terecht.** Ze worden nu alleen nog in de preview getekend.
- **Pauzeknop crashte** (`pause_stream()` bestond niet).
- **Zonder overlay bleven gezichten onbedekt.** Valt nu automatisch terug op pixelen.
- **Andere PNG kiezen tijdens het streamen** toonde op sommige formaten nog de oude overlay (cache werd niet geleegd).
- **Geheugen groeide** tijdens lange streams doordat elke overlaygrootte bewaard werd. Cache is nu begrensd.
- **Gezichten half buiten beeld** werden naar binnen geschoven, waardoor het masker naast het gezicht kon vallen.
- **Virtuele camera tijdens het streamen aanzetten** deed niets; aan/uit werkt nu live.
- **Preview liep steeds verder achter** als het scherm trager was dan de camera (frames stapelden op). De GUI toont nu altijd het nieuwste frame.
- GUI-updates vanuit de achtergrondthread vervangen door een thread-veilige berichtenrij.
- Leeg of half ingetypt *Max Faces*-veld gaf een foutmelding.
- Mislukte modeldownload liet een kapot bestand achter, waardoor de tool daarna nooit meer startte. Nu met tweede downloadbron en controle.
- Grijswaarden-PNG’s als overlay crashten.
- Niet-vierkante overlays werden uitgerekt; beeldverhouding blijft nu behouden.

### Nieuw
- Modi Pixelate, Blur en Black naast Overlay.
- *Smart persistence*: valse detecties verdwijnen snel, gevolgde gezichten blijven lang afgedekt.
- Masker groeit geleidelijk als een gezicht kwijt is.
- *Detect at*: detectie op lagere resolutie voor meer FPS.
- Preview verbergen zonder de stream te stoppen.
- Virtuele camera neemt de resolutie en FPS van de webcam over; op Linux werkt v4l2loopback.
- MJPG-modus bij 1080p, waardoor veel USB-webcams echt 30 fps halen.
- Headless tests (`tests/`).
- `requirements.txt` in plaats van automatische `pip install` bij het opstarten.

## 1.0.0
- Eerste versie: dual-window GUI, YuNet-detectie, Hongaarse tracking, PNG-overlay, OBS-virtuele camera.
