# Pi-Star Control

Pi-Star Control je jednoduchá aplikace pro správu MMDVM hotspotu na Pi-Staru.
Nad jedním běžícím hotspotem staví tři vrstvy ovládání:

- webové rozhraní pro přehled a správu konfigurace
- REST API pro integrace a vzdálené ovládání
- Telegram bota pro rychlé přepínání sítí

## Co projekt umí

- přepínat mezi uloženými host profily, například `host1` a `host2`
- po startu rozpoznat, který profil je právě aktivní
- zobrazovat aktuální volací znak a talkgroup v reálném čase
- zobrazit základní údaje z aktivního profilu, aktuálně `Callsign` a `Id` ze sekce `[General]`
- upravovat `config/app.ini` z webu nebo přes API
- upravovat jednotlivé host soubory samostatně
- přepínat profily i přes Telegram příkazy a tlačítka

## Dokumentace

Podrobnější popis najdeš v [docs/readme.md](docs/readme.md):

- [REST API](docs/api.md)
- [Webové rozhraní](docs/web.md)
- [Telegram bot](docs/telegram.md)
