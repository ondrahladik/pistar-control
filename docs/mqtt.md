# MQTT

[Zpět na přehled](./readme.md)

MQTT integrace publikuje aktuální stav aplikace a současně umí přijímat příkazy pro přepnutí sítě.
Je vhodná pro Home Assistant, Node-RED nebo vlastní monitoring či vlastní IoT řešení.

## Konfigurace

Nastavení je v sekci `mqtt` v `config/app.ini`:

- `enabled`: zapíná nebo vypíná MQTT publikaci
- `server`: hostname nebo IP adresa brokeru
- `port`: TCP port brokeru, výchozí `1883`
- `username`: volitelné uživatelské jméno
- `password`: volitelné heslo
- `topic_pub`: cílový topic pro stavové zprávy
- `topic_sub`: topic, na kterém aplikace naslouchá příkazům

Publikace je aktivní jen pokud je `enabled=true` a zároveň je vyplněný `server` a `topic_pub`.
Příjem příkazů je aktivní jen pokud je `enabled=true` a zároveň je vyplněný `server` a `topic_sub`.

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

## MQTT příkazy

Na `topic_sub` můžeš posílat čistý textový příkaz bez `/`. Například `bm` pro přepnutí na profil s aliasem `BM` je to zkrácená verze názvu profilu pro pohodlné ovládání přes MQTT.

Alias se vyhodnocuje stejně jako u Telegramu, tedy podle sekce `aliases`.
Pokud máš například `host1 = BM`, stačí do MQTT poslat payload `bm`.

## Poznámky

- publikace používá jednoduchý MQTT publish bez TLS
- publish připojení se navazuje pro každé odeslání zvlášť
- subscribe běží trvale na pozadí nad jedním otevřeným MQTT spojením
- přihlašovací údaje jsou volitelné
