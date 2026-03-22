# Webové rozhraní

[Zpět na přehled](./readme.md)

Webové UI je postavené nad Flaskem a používá stejné `/api/*` endpointy jako externí klienti.

## Přihlášení

- nepřihlášený uživatel je přesměrován na `/login`
- přihlášení probíhá přes `POST /auth/login`
- po úspěchu se do session uloží stejný token, jaký používá API
- odhlášení řeší `POST /auth/logout`

## Stránky

### `/`

Domovská stránka funguje jako dashboard:

- každou vteřinu se načítá `/api/status`
- zobrazuje aktuální volací znak a talkgroup
- pod aktuálními hodnotami ukazuje tabulku posledních 10 dokončených volání
- do tabulky se volání zapíše až po ukončení hovoru a každá volačka je v ní jen jednou, vždy svým posledním spojením
- ukazuje právě aktivní profil a základní hodnoty `Callsign` a `Id`
- umožňuje jedním kliknutím přepnout profil přes `POST /api/network`
- stejná historie je dostupná i přes `GET /api/recent-calls`

### `/config`

Konfigurační stránka spravuje dvě vrstvy dat:

- `config/app.ini` po sekcích `api`, `aliases`, `telegram` a `mqtt`
- jednotlivé host soubory načtené přes `/api/hosts/<name>`

Uživatel může:

- upravit port, token a Telegram nastavení
- zapnout nebo vypnout MQTT publikaci samostatným přepínačem
- nastavit MQTT broker, port, přihlašovací údaje, publish topic i subscribe topic
- měnit aliasy profilů
- otevřít každý host soubor zvlášť a uložit ho samostatně

### `/docs`

Interní stránka s rychlým přehledem endpointů, návratových stavů a vazby mezi UI a API.

## Bezpečnostní model

- UI stránky nejsou veřejné bez přihlášení
- `/api/*` endpointy přijímají Bearer token
- přihlášená session může stejné API používat i bez explicitní Authorization hlavičky
