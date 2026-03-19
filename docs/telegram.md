# Telegram bot

[Zpět na přehled](./readme.md)

Telegram integrace funguje jako lehké dálkové ovládání nad stejným API, které používá webové rozhraní.

## Co umí

- vytvořit jeden dashboard message v definovaném chatu
- průběžně aktualizovat aktivní profil, volací znak, talkgroup a čas poslední změny
- přepínat profily přes inline tlačítka
- přepínat profily i pomocí aliasových příkazů, například `/sit1`
- po zpracování příkazu původní zprávu smazat a udržovat chat čistý

## Jak se zapíná

Nastavení je v sekci `telegram` v `config/app.ini`:

- `enabled=true`
- `bot_token=<telegram token>`
- `chat_id=<cilovy chat, volitelne>`
- `thread_id=<volitelne, pro forum topics>`

Pokud chybí `bot_token`, bot zůstane neaktivní.
Pokud `chat_id` nevyplníš, bot se při prvním přijatém příkazu naváže na daný chat a po restartu si ho zapamatuje.

## Aliasové příkazy

Příkazy se odvozují z aliasů definovaných v sekci `aliases`.
Normalizace odstraní diakritiku a speciální znaky, takže z lidského názvu profilu vznikne krátký příkaz vhodný pro Telegram.

## Chování

- bot běží na pozadí ve vlastním vlákně
- po prvním použití si pamatuje `chat_id`, `thread_id` i dashboard message, aby po restartu nepřidával další zprávy
- dashboard se obnoví po změně stavu i po přepnutí profilu
- tlačítka i příkazy ve výsledku volají interní API pro přepnutí sítě
- změny stavu mohou současně spouštět i další integrace, například MQTT publikaci
