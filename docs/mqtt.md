# MQTT

[Zpět na přehled](./readme.md)

MQTT integrace publikuje aktuální stav aplikace do jednoho zvoleného topicu.
Je vhodná pro Home Assistant, Node-RED nebo vlastní monitoring.

## Konfigurace

Nastavení je v sekci `mqtt` v `config/app.ini`:

- `enabled`: zapíná nebo vypíná MQTT publikaci
- `server`: hostname nebo IP adresa brokeru
- `port`: TCP port brokeru, výchozí `1883`
- `username`: volitelné uživatelské jméno
- `password`: volitelné heslo
- `topic`: cílový topic pro stavové zprávy

Publikace je aktivní jen pokud je `enabled=true` a zároveň je vyplněný `server` a `topic`.

## JSON payload

Každá zpráva se odesílá jako JSON:

```json
{
  "network": "BM",
  "callsign": "OK1ABC",
  "talkgroup": "230",
  "time": "18:42:11"
}
```

Pole `network` obsahuje alias aktivního profilu, ne interní název `host1` nebo `host2`.
Pokud právě není aktivní hovor, `callsign` a `talkgroup` mají hodnotu `null`.

## Kdy se zprávy odesílají

- po změně aktivního profilu
- po zachycení nové volací značky a talkgroup z MMDVM logu
- po ukončení hovoru
- po restartu služby, pokud je stav známý a MQTT je nastavené

## Poznámky

- publikace používá jednoduchý MQTT publish bez TLS
- připojení se navazuje pro každé odeslání zvlášť
- přihlašovací údaje jsou volitelné
