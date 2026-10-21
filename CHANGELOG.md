# Changelog

## 4.5.2
- Camera-app: kleurcorrectie wordt **per camera** onthouden (bijv. omwisselen voor de achtercamera, automatisch voor de selfiecamera). Een eerder gekozen instelling blijft gelden voor de achtercamera
- Onderaan de instellingen staat welk beeldformaat de camera levert, handig bij het melden van kleurproblemen

## 4.5.1
- Camera-app: **kleurcorrectie** voor telefooncamera's die rood en blauw omgewisseld leveren (alles blauw; gezien met de achtercamera in de Android-app). Wordt automatisch herkend door de ruwe camerapixels te vergelijken met het beeld op het scherm; in de instellingen ook met de hand aan of uit te zetten

## 4.5.0 – Licentie en F-Droid
- **Licentie: GPL-3.0-or-later** (`LICENSE`); onderdelen van derden in `THIRD_PARTY_NOTICES.md`
- Android-app voorbereid op F-Droid: ONNX Runtime van npm in plaats van uit de repo, vaste versie 1.0.0 (versionCode 100), catalogusgegevens en schermafbeeldingen in `fastlane/`, concept-bouwrecept en stappenplan in `android-app/FDROID.md`
- `tools/make_dynamic_yunet.py`: maakt het gezichtsmodel van de browsertools byte-voor-byte na uit het officiële OpenCV-model

## 4.4.0
- **Beschermende blur** ook in de live Face Anonymizer (*Protective blur*) en de browserextensie 1.2.0 (*Beschermende blur*): heel beeld vaag zolang er geen gezicht gevonden wordt. Daar standaard uit

## 4.3.0
- Camera-app (web en Android): **beschermende blur**, met het schildje bovenin aan en uit te zetten. Wordt er geen gezicht gevonden, dan wordt het hele beeld vervaagd (ook in foto's en opnames); uitzetten voor beelden zonder mensen

## 4.2.1
- Standaard-overlay in alle tools is nu een neutrale "Your image here"-afbeelding in plaats van het CA-logo; kies je eigen logo in de tool of vervang `assets/overlay.png`

## 4.2.0 – Android-app
- **FA Camera als Android-app (APK)** in `android-app/`, gebouwd met Capacitor rond de camera-app
- Bewaart direct in de galerij (map *FA Camera*), deelt via het Android-deelmenu, houdt het scherm aan, terugknop sluit eerst panelen
- GitHub Actions bouwt de APK bij elke wijziging en zet hem op de Releases-pagina

## 4.1.0 – Face Anonymizer Camera
- **Nieuwe app voor Android en iPhone** (`camera/`): filmen en fotograferen met gezichten al afgedekt, als web-app op je beginscherm te zetten en offline te gebruiken
- Opname vanaf het bewerkte beeld; heel beeld vervaagd zolang de herkenning niet klaar is
- Foto's worden bij het maken extra grondig doorzocht
- Bewaren in Foto's (iPhone) of Downloads (Android), of delen
- Webtool linkt naar de camera-app; GitHub Pages publiceert beide

## 4.0.1
- Live-app: is de virtuele-cameradriver niet geladen, dan laadt de app hem zelf (met wachtwoordvenster) en probeert het opnieuw. Lukt het niet, dan zegt de statusregel waarom: driver niet geïnstalleerd, Secure Boot, geannuleerd of in gebruik
- README: *Problemen oplossen: virtuele camera*
- `install.sh` zet bij Secure Boot de goedkeuring van de driver zelf klaar en laat je daarvoor zelf een wachtwoord kiezen

## 4.0.0 – Face Anonymizer for AV
- **Nieuwe app** `av_anonymizer.py` voor opgeslagen video's, beeldreeksen en losse foto's, met eigen snelkoppeling
- Gezichten worden over de tijd gevolgd: missers worden opgevuld langs de bewegingsbaan, met marge voor en na; losse valse treffers vallen weg
- Geluid blijft behouden; metadata (GPS, titel, toestel) wordt verwijderd; telefoonvideo's worden rechtop gezet
- Nalopen: door de video bladeren, opgevulde stukken controleren, maskers weghalen of toevoegen, ongedaan maken, opnieuw opslaan
- Ook zonder venster te gebruiken (opdrachtregel)
- **Alle tools:** een doorzichtige rand rond de overlay wordt weggeknipt, zodat het logo het hele maskervlak bedekt (het standaardlogo dekte daardoor ~15% te weinig af)

## 3.0.0 – Foto Anonymizer
- **Nieuwe desktop-app** `photo_anonymizer.py`: anonimiseert een hele map foto's, met nalopen en handmatig corrigeren; ook zonder venster te gebruiken
- **Nieuwe webtool** (`web/`): zelfde functie in de browser, foto's blijven op je computer; download als ZIP
- Gezichten zoeken op meerdere schalen en in tegels, voor zowel close-ups als publiek ver weg
- Metadata (GPS, camera) wordt verwijderd; telefoonfoto's worden rechtop gezet; HEIC → JPG
- Gedeelde kern `face_core.py` (model en maskers) voor alle Python-tools
- `install.sh` installeert beide apps met elk een eigen snelkoppeling en bouwt de webtool
- GitHub Pages-workflow publiceert de webtool automatisch
- Starter meldt geen fout meer bij afsluiten door uitloggen of herstarten

## 2.2.0
- **Mirror overlay** in de desktopversie, live aan en uit te zetten (zelfde optie als in de browserextensie)

## 2.1.0
- `install.sh` voor Linux: installeert alles in één keer, inclusief virtuele camera die na een herstart beschikbaar blijft
- Snelkoppeling in het app-menu en op het bureaublad; starten zonder terminal
- Foutmelding in een venster als de app niet start; logboek in `~/.cache/face-anonymizer/`
- Kan niet per ongeluk twee keer tegelijk starten (de camera is maar door één programma te gebruiken)
- `uninstall.sh` om alles weer te verwijderen
- App-icoon; beide vensters vallen onder één icoon in het dock

## Browserextensie 1.1.0
- **Sneller**: het model draait nu op het echte beeldformaat (bijv. 480×288) in plaats van een opgevuld vierkant van 640×640. Detectie gaat daardoor ongeveer 3× zo snel.
- **Keuze voor snelheid** in de popup: Snel / Normaal / Nauwkeurig
- **Masker beweegt mee**: tussen twee detecties wordt de positie voorspeld uit je bewegingsrichting, en het masker wordt iets groter bij snelle bewegingen
- **Geen spookmaskers meer** bij snelle bewegingen: gezichten worden ook op afstand gekoppeld en dubbele maskers worden opgeruimd
- **Overlay spiegelen** als optie

## Browserextensie 1.0.0
- Chrome/Edge-extensie die de webcam in webapps vervangt door een geanonimiseerd beeld
- YuNet via ONNX Runtime Web; decodering geverifieerd tegen OpenCV
- Overlay, pixels, blur, zwart; eigen PNG via de popup; instellingen gelden live
- Fail-safe: heel beeld vervaagd zolang de detector niet klaar is of niet reageert
- Detector herstelt automatisch als een website de verborgen frame verwijdert

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
