# Pi-Star Control

Pi-Star Control je jednoduchá aplikace pro správu MMDVM hotspotu na Pi-Staru.
Nad jedním běžícím hotspotem staví tři vrstvy ovládání:

- webové rozhraní pro přehled a správu konfigurace
- REST API pro integrace a vzdálené ovládání
- Telegram bota pro rychlé přepínání sítí
- MQTT publikaci aktuálního stavu do externích systémů

## Co projekt umí

- přepínat mezi uloženými host profily, například `host1` a `host2`
- po startu rozpoznat, který profil je právě aktivní
- zobrazovat aktuální volací znak a talkgroup v reálném čase a také posledních 10 volajicích
- zobrazit základní údaje z aktivního profilu, aktuálně `Callsign` a `Id`
- upravovat `config/app.ini` z webu nebo přes API
- upravovat jednotlivé host soubory samostatně
- přepínat profily i přes Telegram a MQTT
- odesílat aktuální síť, volačku, talkgroup a čas do Telegramu a MQTT topicu jako JSON

## Automatická instalace

Pro rychlé nasazení na Pi-Star můžeš použít připravené skripty pro instalaci, aktualizaci i odinstalaci. Skripty automaticky řeší běžné kroky jako přípravu prostředí, práci s repozitářem a obsluhu služby.

Instalace:

```bash
curl -s https://dmrhub.eu/install.sh | sudo bash
```

Aktualizace:

```bash
curl -s https://dmrhub.eu/update.sh | sudo bash
```

Odinstalace:

```bash
curl -s https://dmrhub.eu/remove.sh | sudo bash
```

Instalace trvá přibližně 4 minuty. Manuální instalace je popsána v dokumentaci, ale doporučuji použít automatickou instalaci, pokud nejsi zkušený s Linuxem.

## Výchozí nastavení

- **API token**: `pistar`
- **Port aplikace**: `5000`
- **URL aplikace**: http://pi-star.local:5000

Token doporučuji změnit pro lepší zabezpečení.

## Dokumentace

Podrobnější popis najdeš v [docs/readme.md](docs/readme.md):

- [Instalace](docs/install.md)
- [Konfigurace](docs/config.md)
- [REST API](docs/api.md)
- [Webové rozhraní](docs/web.md)
- [Telegram bot](docs/telegram.md)
- [MQTT](docs/mqtt.md)
