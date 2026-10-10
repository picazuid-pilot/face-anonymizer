# 🎭 Face Anonymizer – browserextensie

Anonimiseert gezichten in je webcambeeld **voordat een website het te zien krijgt**. Zet de extensie aan, open Google Meet, Zoom in de browser, Teams (web), YouTube Studio, StreamYard of een andere webapp, en kies gewoon je normale camera. De website krijgt automatisch het geanonimiseerde beeld.

Werkt in **Chrome en Edge** (versie 111 of nieuwer). Firefox en Safari ondersteunen de benodigde video-API nog niet.

## Installeren (ontwikkelaarsmodus)

1. Download of clone deze repository.
2. Ga in Chrome naar `chrome://extensions` (Edge: `edge://extensions`).
3. Zet rechtsboven **Ontwikkelaarsmodus** aan.
4. Klik **Uitgepakte extensie laden** en kies de map `browser-extension`.
5. Pin het icoon in de werkbalk; via de popup stel je alles in.

Stond de camera al aan in een tabblad? Herlaad dat tabblad eenmalig.

## Hoe het werkt

```
camera ──► extensie (in de pagina) ──► gezichten afgedekt ──► website
                │          ▲
                ▼          │ boxen
        verborgen extensie-frame: YuNet-model (ONNX Runtime, WebAssembly)
```

- De extensie vervangt `navigator.mediaDevices.getUserMedia` vóórdat de website laadt. De website krijgt een nieuwe videotrack; het ruwe beeld blijft binnen de extensie.
- Gezichten worden gevonden met hetzelfde YuNet-model als de Python-tool, met dezelfde tracking, *slim vasthouden* en groeiende maskers bij een kwijtgeraakt gezicht.
- Alles draait lokaal in je browser. Er gaat geen beeld naar een server.

### Veiligheid: bij twijfel dicht

- Zolang de detector nog laadt of niet reageert, wordt het **hele beeld vervaagd** (uit te zetten in de popup, niet aangeraden).
- Zonder overlay valt de modus Overlay terug op pixelen.
- Een frame dat niet verwerkt kan worden, wordt overgeslagen in plaats van onbewerkt doorgestuurd.
- Ondersteunt de browser de techniek niet terwijl de extensie aan staat, dan weigert de camera met een melding in plaats van onbewerkt beeld te geven.

## Instellingen

| Instelling | Uitleg |
|---|---|
| Aan/uit | Live te schakelen, ook tijdens een gesprek |
| Overlay / Pixels / Blur / Zwart | Hoe gezichten worden afgedekt. Bij Overlay kun je een eigen PNG kiezen |
| Maskergrootte | Grootte van het masker t.o.v. het gezicht |
| Zekerheid | Hoger = minder valse vlekken |
| Min. grootte | Kleinste gezicht in pixels |
| Vasthouden | Hoeveel detecties een masker blijft staan nadat een gezicht kwijt is |
| Slim vasthouden | Losse valse detecties verdwijnen na 5 detecties, gevolgde gezichten blijven |
| Snel / Normaal / Nauwkeurig | Grootte van het beeld waarop gezichten gezocht worden (320, 480 of 640 px). Sneller volgt beweging beter, nauwkeuriger vindt kleinere gezichten |
| Overlay spiegelen | Spiegelt het logo. Meet, Zoom en Teams spiegelen alleen je **eigen** voorbeeld; de anderen zien het logo gewoon goed. Gebruik dit dus alleen als je zelf ook gespiegeld uitzendt, of zet in Meet bij Video het spiegelen van je eigen beeld uit |

## Beperkingen

- Alleen voor **webapps in de browser**. De desktop-apps van Zoom, Teams, OBS enz. gebruiken de camera buiten de browser om; gebruik daarvoor de Python-tool met virtuele camera (zie de hoofdmap).
- Gezichten worden gezocht op een verkleinde versie van het beeld (standaard 480 px). Heel kleine gezichten ver weg (groot publiek) vindt de Python-tool op volle resolutie beter.
- Geen enkele detector is perfect. Test vooraf met je eigen camera en licht.

## Testen zonder te installeren

`test/harness.html` bootst de extensie na in een gewone pagina:

```bash
cd browser-extension
python -m http.server 8123
# open http://localhost:8123/test/harness.html
```

## Onderdelen van derden

- [ONNX Runtime Web](https://github.com/microsoft/onnxruntime) 1.30 (`lib/`), MIT-licentie
- [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) 2023mar (`models/yunet.onnx`), MIT-licentie
