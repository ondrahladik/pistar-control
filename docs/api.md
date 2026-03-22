# REST API

[Zpět na přehled](./readme.md)

HTTP API slouží pro čtení stavu aplikace, historie posledních volání, správu `app.ini` a úpravu host profilů.
Všechny `/api/*` endpointy jsou chráněné Bearer tokenem z `config/app.ini`.

## Autentizace

Použij HTTP hlavičku:

```http
Authorization: Bearer <api-token>
```

Bez platného tokenu server vrací `401 Unauthorized`.  
  
Vychozí token je `pistar`, ale doporučuji ho změnit pro lepší zabezpečení.

## Endpointy

### `GET /api/status`

Vrátí aktuální aktivní profil, jeho alias, základní údaje a poslední zachycenou aktivitu.

Typická odpověď obsahuje:

- `current_network`
- `current_network_label`
- `current_network_settings.callsign`
- `current_network_settings.id`
- `active_call`
- `recent_calls`
- `last_update_at`

`recent_calls` obsahuje maximálně 10 posledních dokončených volání, od nejnovějšího po nejstarší. Do historie se položka zapíše až po ukončení hovoru a každá volačka se v seznamu drží jen jednou, vždy jen svým posledním spojením. Každá položka má:

- `callsign`
- `talkgroup`
- `time`
- `duration`
- `loss`
- `ber`

### `GET /api/recent-calls`

Vrátí stejnou historii posledních 10 dokončených volání i samostatně.

Typická odpověď:

```json
{
  "recent_calls": [
    {
      "callsign": "OK1ABC",
      "talkgroup": "230",
      "time": "18:42:11",
      "duration": "1.2",
      "loss": "0",
      "ber": "0.0"
    }
  ]
}
```

### `GET /api/networks`

Vrátí seznam dostupných host profilů a jejich aliasů pro zobrazení v UI.

### `POST /api/network`

Přepne aktivní profil.

Payload:

```json
{
  "network": "host1"
}
```

Chyby:

- `400` při chybějícím názvu profilu
- `404` pokud profil neexistuje
- `500` pokud se přepnutí nepodaří dokončit

### `GET /api/config`

Načte `config/app.ini` po sekcích a klíčích.

### `POST /api/config`

Uloží nový obsah `config/app.ini`.
Payload musí být objekt ve tvaru:

```json
{
  "config": {
    "api": {
      "port": "5000",
      "token": "pistar"
    }
  }
}
```

Při ukládání se prázdné hodnoty u citlivých polí zachovávají z původní konfigurace:

- `api.token`
- `telegram.bot_token`
- `telegram.chat_id`
- `mqtt.password`

### `GET /api/hosts/<name>`

Vrátí obsah konkrétního host profilu:

- `id`
- `label`
- `content`

### `POST /api/hosts/<name>`

Uloží nový text host souboru.

Payload:

```json
{
  "content": "..."
}
```

## Poznámky

- API podporuje `OPTIONS` na `/api/<path>` kvůli CORS.
- Server povoluje `GET`, `POST` a `OPTIONS`.
- Webové UI může používat stejné endpointy i bez Bearer hlavičky, pokud je uživatel přihlášený v session.
- MQTT nastavení se ukládá ve stejné sekci `config` přes `GET /api/config` a `POST /api/config`.
