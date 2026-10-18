# 🎭 Face Anonymizer

Anonimiseert gezichten live in je webcambeeld en stuurt het resultaat naar een **virtuele camera**. Bedoeld voor podcasts, interviews en livestream-events waarbij het publiek of gasten anoniem in beeld moeten blijven.

Kies daarna gewoon de virtuele camera als bron in OBS, Zoom, Teams, Google Meet, YouTube Studio enz.

- Gezichtsdetectie met [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (OpenCV), snel genoeg voor 1080p op een gewone laptop
- Tracking met de Hongaarse methode, zodat een gezicht een vast ID houdt en een korte detectie-misser het gezicht niet blootgeeft
- Vier anonimiseringsmodi: **Overlay** (eigen PNG, bijv. een logo), **Pixelate**, **Blur**, **Black**
- Twee vensters: bediening en een schaalbare preview
- Debug-kaders zie je alleen in de preview, **nooit** in de stream

https://github.com/user-attachments/assets/024daca7-4c85-42a7-befd-ff649e81f6b3

[![Anonymizer for Desktop, webbrowser, Zoom, Meet, Photo's](https://img.youtube.com/vi/MOAy1L4CMFw/0.jpg)](https://www.youtube.com/watch?v=MOAy1L4CMFw)


<img width="1822" height="863" alt="Blindfolded Mid-Century Meeting" src="https://github.com/user-attachments/assets/6f539450-b3ab-4ea7-af2c-c94842111238" />
<img width="649" height="355" alt="Screenshot from 2026-10-11 22-13-50" src="https://github.com/user-attachments/assets/0b10df03-c978-4fb8-961c-70baa0e0dd37" />



## Welke tool heb je nodig?

| Je wilt… | Gebruik |
|---|---|
| Live webcambeeld anonimiseren voor OBS, Zoom, Teams of Meet | **Face Anonymizer** (desktop-app, deze pagina) |
| Hetzelfde, maar alleen in Meet, Zoom of Teams in de browser | **[Browserextensie](browser-extension/)** |
| Een map vol foto's anonimiseren op je eigen computer | **[Foto Anonymizer](#-foto-anonymizer)** (desktop-app) |
| Foto's anonimiseren zonder iets te installeren | **[Foto Anonymizer webtool](#webtool)** |
| Opgeslagen video's, beeldreeksen (genummerde beelden) of losse foto's anonimiseren | **[Face Anonymizer for AV](#-face-anonymizer-for-av)** (desktop-app) |

Alle tools gebruiken hetzelfde gezichtsmodel en werken volledig lokaal: er gaan geen beelden of video's naar een server.

## Installatie

### Linux (Ubuntu, Debian, Mint, Fedora, Arch) – automatisch

Eenmalig in een terminal, vanuit de map van deze repository:

```bash
git clone https://github.com/picazuid-pilot/face-anonymizer.git
cd face-anonymizer
./install.sh
```

Het script:

1. installeert Python, Tk en de virtuele-camera-driver (*v4l2loopback*);
2. zet de app met een eigen Python-omgeving in `~/.local/share/face-anonymizer`;
3. downloadt het gezichtsmodel vooraf;
4. stelt de virtuele camera **"Face Anonymizer"** zo in dat hij na elke herstart beschikbaar is;
5. maakt een snelkoppeling in het **app-menu** en op het **bureaublad**.

Daarna start je Face Anonymizer gewoon via het app-menu of het bureaublad; een terminal is niet meer nodig. Gaat er iets mis bij het starten, dan krijg je een venster met de foutmelding (het volledige logboek staat in `~/.cache/face-anonymizer/`).

| | |
|---|---|
| Bijwerken | `git pull && ./install.sh` |
| Verwijderen | `./uninstall.sh` |
| Zonder vragen | `./install.sh --yes` |
| Zonder virtuele camera | `./install.sh --no-virtualcam` |

**Secure Boot:** staat Secure Boot aan, dan vraagt Ubuntu bij het installeren van de driver om een wachtwoord. Na de herstart verschijnt een blauw scherm: kies *Enroll MOK* en voer dat wachtwoord in. Daarna werkt de virtuele camera.

### Windows en macOS – handmatig

Python 3.10 of nieuwer en [OBS Studio](https://obsproject.com/) (alleen voor de driver van de virtuele camera; OBS hoeft niet open te staan).

```bash
pip install -r requirements.txt
python face_anonymizer.py
```

Op macOS moet je de virtuele camera één keer in OBS starten om hem te registreren. Op Windows zet je de virtuele camera in OBS zelf **niet** aan; deze tool gebruikt hem.

### Heb ik OBS nodig?

Nee, niet om naar Zoom, Meet of Teams te gaan. De virtuele camera verschijnt in die apps als een gewone webcam met de naam **"Face Anonymizer"**. Op Linux levert *v4l2loopback* die camera; op Windows en macOS moet OBS geïnstalleerd zijn voor de driver. OBS gebruik je alleen als je zelf een livestream opbouwt; daar kies je de virtuele camera dan als *Video-opnameapparaat*.

## Gebruik

1. Kies het cameranummer (meestal `0`) en druk op **▶ Start**.
2. Vink **Enable Virtual Camera** aan. Je kunt dit ook tijdens het streamen aan- en uitzetten.
3. Kies in Zoom, Meet, Teams of OBS de camera **"Face Anonymizer"**.
   Op Linux toont Chrome/Meet de camera pas als er beeld op staat: start dus eerst deze tool en vink de virtuele camera aan, en open of herlaad daarna Meet.
4. Zet **Show debug boxes** gerust aan om te tunen: de kaders komen niet in de stream terecht.
5. Sluit je het previewvenster, dan loopt de stream gewoon door en bespaar je rekenkracht.

Gebruik je de virtuele camera in de browser, zet dan de browserextensie uit; anders wordt het beeld twee keer bewerkt.

Standaard wordt `assets/overlay.png` als overlay geladen. Met **📁 Select PNG** kies je een andere. Transparante PNG’s werken het best; zorg dat het deel dat over het gezicht valt volledig dekkend is.

### Instellingen

| Instelling | Wat het doet | Tip |
|---|---|---|
| Scale | Grootte van het masker t.o.v. het gezicht | 1.6–2.0 dekt ook haar en oren |
| Confidence | Minimale zekerheid van een detectie | Hoog (0.6–0.8) = minder valse vlekken op de achtergrond |
| Min Size | Kleinste gezicht in pixels | Verhoog bij een vol publiek op afstand als er ruis ontstaat |
| Persistence | Hoe lang (frames) een masker blijft staan als het gezicht even niet gedetecteerd wordt | Zie hieronder |
| Smart persistence | Gezichten die nog geen 5 keer gezien zijn, verdwijnen al na 5 frames | Laat aan |
| Detect at | Detecteren op lagere resolutie | `960` of `1280` geeft veel meer FPS bij 1080p; `Full` vindt kleine gezichten verder weg beter |
| Mode | Overlay / Pixelate / Blur / Black | Zonder geladen overlay wordt automatisch gepixeld |
| Mirror overlay | Spiegelt het logo | Zoom, Meet en Teams spiegelen alleen je **eigen** voorbeeld; de anderen zien het logo gewoon goed. Zet dit alleen aan als je ook gespiegeld uitzendt |

**Waarom hoge confidence + lage persistence zo goed werkt:** bij lage confidence ontstaan af en toe valse detecties (een lamp, een poster), en met hoge persistence blijven die maskers lang hangen. *Smart persistence* lost precies dat op: losse valse detecties verdwijnen snel, terwijl echte gezichten die al een tijd gevolgd worden wél lang afgedekt blijven. Je kunt de persistence daardoor weer wat hoger zetten (bijv. 20–30) zonder rommel, wat veiliger is als iemand even wegdraait. Een kwijtgeraakt gezicht krijgt bovendien een masker dat langzaam groeit, zodat het nog bedekt is als de persoon beweegt.

### Problemen oplossen: virtuele camera (Linux)

**Melding "No v4l2 loopback device found"** of **"Face Anonymizer" staat niet in de cameralijst van Zoom**: de driver voor de virtuele camera is niet geladen. De app probeert dit zelf op te lossen en vraagt daarvoor je wachtwoord. Lukt dat niet, dan staat in de statusregel waarom. Zelf nagaan:

```bash
modinfo v4l2loopback | head -3   # foutmelding = driver niet geïnstalleerd
lsmod | grep v4l2loopback        # leeg = niet geladen
mokutil --sb-state               # "SecureBoot enabled" = zie hieronder
ls /dev/video*                   # /dev/video10 hoort erbij te staan
```

| Oorzaak | Oplossing |
|---|---|
| Driver niet geïnstalleerd (nieuwe computer, of bij de installatie "nee" gekozen) | `./install.sh` opnieuw draaien, of `sudo apt install v4l2loopback-dkms linux-headers-$(uname -r)` |
| **Secure Boot** blokkeert de driver (`Key was rejected by service`) | `sudo mokutil --revoke-import` en dan `sudo mokutil --import /var/lib/shim-signed/mok/MOK.der`, kies een eenmalig wachtwoord en herstart. Druk in het blauwe scherm *Perform MOK management* **direct op een toets** (het verdwijnt na 10 seconden) en kies **Enroll MOK → Continue → Yes**, wachtwoord, **Reboot**. `./install.sh` doet dit ook voor je |
| Na een kernelupdate werkt het niet meer | `sudo apt install linux-headers-$(uname -r)` en `sudo dpkg-reconfigure v4l2loopback-dkms` |
| Driver geladen, maar niet zichtbaar in Zoom | Zoom pas starten (of helemaal afsluiten en opnieuw openen) **nadat** de virtuele camera aanstaat en beeld geeft. Zoom zoekt alleen bij het opstarten naar camera's |

Met de hand laden: `sudo modprobe v4l2loopback devices=1 video_nr=10 exclusive_caps=1 card_label="Face Anonymizer"`

## Privacy en betrouwbaarheid

Geen enkele gezichtsdetector is 100% betrouwbaar. Profielen, handen voor het gezicht, sterk tegenlicht en hele kleine gezichten kunnen gemist worden. Test daarom vooraf in de echte ruimte met het echte licht, en overweeg bij gevoelige events extra maatregelen: camerastandpunt achter het publiek, een iets grotere *Scale*, of in OBS een vaste vertraging zodat je kunt ingrijpen.

Alle verwerking gebeurt lokaal; er worden geen beelden verstuurd.

## Tests

```bash
pip install pytest
python -m pytest tests/
```

De tests draaien zonder camera of scherm. Ze controleren onder meer dat debug-kaders nooit in de stream komen, dat elke afdekmodus het gezicht echt bedekt, dat kleine en grote gezichten gevonden worden, dat metadata verdwijnt en dat telefoonfoto's rechtop komen.

## 🖼 Foto Anonymizer

Maakt alle gezichten op een map vol foto's onherkenbaar, bijvoorbeeld foto's van een bijeenkomst die je wilt delen of publiceren.

- **Originelen blijven altijd bewaard**: de resultaten komen in een aparte map (standaard `<map>_anoniem`), met dezelfde submappen
- **Logo, pixels, blur of zwart vlak**, dezelfde keuzes als bij de live-tool; ook overlay spiegelen
- **Metadata wordt verwijderd**: GPS-locatie, cameratype en datum gaan niet mee
- **Telefoonfoto's** worden rechtop gezet; iPhone-foto's (HEIC) worden JPG
- **Ook kleine gezichten**: er wordt op meerdere schalen gezocht; *Grondig* zoekt daarnaast in stukken van de foto op volle resolutie, voor publiek ver weg
- **Nalopen**: foto's zonder gevonden gezicht worden gemarkeerd. Klik een foto aan om maskers weg te halen (klik) of toe te voegen (slepen); de foto wordt direct opnieuw opgeslagen

### Desktop-app

Na `./install.sh` staat **Foto Anonymizer** in je app-menu en op je bureaublad. Kies een map, kies de afdekking en druk op **Start**. Dubbelklik daarna op een foto in de lijst om hem na te lopen.

Zonder venster, bijvoorbeeld voor een script:

```bash
python photo_anonymizer.py ~/Fotos/bijeenkomst              # → ~/Fotos/bijeenkomst_anoniem
python photo_anonymizer.py BRON DOEL -r --mode pixelate --accuracy thorough
python photo_anonymizer.py --help
```

### Webtool

Dezelfde functie in de browser, zonder installatie: sleep foto's of een hele map op de pagina, loop ze na en download alles als ZIP. **De foto's worden niet geüpload**: alles gebeurt in je eigen browser, en de pagina mag technisch gezien geen verbinding maken met andere websites. Getest in Chrome (dus ook Edge), op de computer en op telefoonformaat; Firefox en Safari zijn nog niet getest.

- **Online**: https://picazuid-pilot.github.io/face-anonymizer/ (wordt bij elke wijziging automatisch bijgewerkt via GitHub Pages)
- **Op je eigen website** (bijv. InfinityFree): voer `web/build.sh` uit en zet de inhoud van `dist/web` in een map op je hosting. Er is geen PHP of database nodig. Na `install.sh` staat de gebouwde versie ook al klaar in `~/.local/share/face-anonymizer/web`.

iPhone-foto's (HEIC) kan de browser niet openen; gebruik daarvoor de desktop-app.

### Desktop-app of webtool?

| | Desktop-app | Webtool |
|---|---|---|
| Installatie | `install.sh` | Geen |
| Grote mappen (honderden foto's) | Beter: schrijft direct naar schijf | Prima tot enkele honderden foto's |
| iPhone-foto's (HEIC) | Ja | Nee |
| Mappenstructuur behouden | Ja | Ja (bij een map slepen of kiezen) |
| Snelheid | Sneller | Iets trager |

## 🎬 Face Anonymizer for AV

Anonimiseert gezichten in **opgeslagen video's**, **beeldreeksen** (bijv. `shot_0001.png`, `shot_0002.png` …) en **losse foto's**, voor podcasts, interviews en opnames van bijeenkomsten.

- **Originelen blijven altijd bewaard**: de resultaten krijgen `_anoniem` in de naam en komen in een aparte map (standaard `anoniem` naast je bestanden)
- **Geluid blijft behouden**; de video wordt opnieuw opgeslagen als MP4 (H.264)
- **Metadata wordt verwijderd**: GPS-locatie, titel en toestel gaan niet mee
- **Telefoonvideo's** worden rechtop gezet
- **Logo, pixels, blur of zwart vlak**, ook overlay spiegelen, net als bij de andere tools

### Waarom betrouwbaarder dan live

Live weet de tool alleen wat er al gebeurd is. Bij een opgeslagen video kent hij ook de beelden **erna**:

1. Eerst worden in **alle** beelden de gezichten gezocht.
2. Daarna worden ze over de tijd gevolgd. Wordt een gezicht even gemist (opzij kijken, hand voor het gezicht, bewegingsonscherpte), dan vult de tool dat stuk op langs de baan tussen ervoor en erna. Het masker wordt daar iets groter, omdat de positie minder zeker is.
3. Elk masker verschijnt net iets vóór het gezicht in beeld komt en blijft net iets langer staan.
4. Losse twijfelachtige treffers (bijv. een poster die één beeld lang op een gezicht lijkt) vallen weg.

### Nalopen

Dubbelklik na het verwerken op een video in de lijst:

- **Bladeren** met de schuifregelaar of de pijltjestoetsen
- **Oranje kaders** en de oranje stukjes op de tijdlijn zijn **opgevulde** stukken: daar is het gezicht niet zelf gevonden. Met *Volgend opgevuld stuk* spring je er direct naartoe om ze te controleren
- **Klik op een masker** om het in de hele video weg te halen (bijv. een vals masker op een poster)
- **Sleep over een gemist gezicht** om een masker toe te voegen, vanaf dat beeld voor een in te stellen aantal seconden
- **Ongedaan maken** en daarna **Opnieuw opslaan**

### Gebruik

Na `./install.sh` staat **Face Anonymizer for AV** in je app-menu. Voeg bestanden of een map toe, kies de afdekking en druk op **Start**. Een map met genummerde beelden wordt automatisch als beeldreeks herkend; de uitvoer krijgt dezelfde bestandsnamen.

Zonder venster:

```bash
python av_anonymizer.py opname.mp4                               # → anoniem/opname_anoniem.mp4
python av_anonymizer.py ~/Opnames ~/Shots/scene1 -o ~/Anoniem --speed thorough
python av_anonymizer.py --help
```

| Instelling | Uitleg |
|---|---|
| Snel / Normaal / Grondig | *Snel* zoekt in elk 2e beeld en vult ertussen aan. *Grondig* zoekt ook naar kleine gezichten ver weg, maar is een stuk trager |
| Zekerheid | Hoger = minder valse maskers |
| Missers opvullen | Hoe lang (standaard 1,5 s) een masker blijft staan als een gezicht even niet gevonden wordt |

**Snelheid:** reken op ongeveer 2 tot 4 keer de lengte van de video op een gewone laptop (*Normaal*, 1080p). Een opname van 10 minuten duurt dus zo'n 20 tot 40 minuten. *Snel* scheelt ongeveer een derde.

**Goed om te weten:**
- Beeldreeksen worden als 8-bit opgeslagen; 16-bit PNG/TIFF uit compositing-software verliest dus kleurdiepte.
- Een gezicht dat lang én snel uit beeld beweegt (meer dan ~1 seconde niet te zien terwijl het van richting verandert) kan het opvullen niet precies volgen. Die stukken staan oranje bij het nalopen.

## Browserextensie (Chrome/Edge)

In [`browser-extension/`](browser-extension/) staat een extensie (installatie: zie de [README](browser-extension/README.md); na `install.sh` staat hij ook klaar in `~/.local/share/face-anonymizer/browser-extension`) die in webapps (Google Meet, Zoom in de browser, Teams web, StreamYard, YouTube Studio) je webcambeeld vervangt door een geanonimiseerde versie. Zet hem aan en kies je gewone camera; meer is niet nodig. Hij gebruikt hetzelfde YuNet-model en dezelfde tracking als deze Python-tool.

| | Python-tool | Browserextensie |
|---|---|---|
| OBS, Zoom/Teams desktop-app | ✅ via virtuele camera | ❌ |
| Meet, Zoom/Teams in de browser, YouTube Studio | ✅ via virtuele camera | ✅ direct |
| Installatie | `install.sh` (Linux) of Python + OBS (Windows/macOS) | Extensie laden |
| Kleine gezichten ver weg | Beter (volle resolutie) | Detectie op 320–640 px |

## Roadmap

- **Webpagina** die de webcam in de browser anonimiseert, als *Browserbron* of *Venster-opname* in OBS.

## Overlay-logo

`assets/overlay.png` is het CA-logo (handelsmerk). Vervang het door je eigen afbeelding als je de tool buiten CA-verband gebruikt.

## Licentie

Nog te bepalen.
