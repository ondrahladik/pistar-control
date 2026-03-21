# Telegram bot

[Zpět na přehled](./readme.md)

Telegram integrace funguje jako lehké dálkové ovládání nad stejným API, které používá webové rozhraní.

## Co umí

- vytvořit jeden dashboard message v definovaném chatu
- průběžně aktualizovat aktivní profil, volací znak, talkgroup a čas poslední změny
- přepínat profily přes inline tlačítka
- přepínat profily i pomocí aliasových příkazů, například `/sit1`
- po zpracování příkazu původní zprávu smazat a udržovat chat čistý

## Aliasové příkazy

Příkazy se odvozují z aliasů definovaných v sekci `aliases`.
Normalizace odstraní diakritiku a speciální znaky, takže z lidského názvu profilu vznikne krátký příkaz vhodný pro Telegram.

## Chování

- bot běží na pozadí ve vlastním vlákně
- po prvním použití si pamatuje `chat_id`, `thread_id` i dashboard message, aby po restartu nepřidával další zprávy
- dashboard se obnoví po změně stavu i po přepnutí profilu
- tlačítka i příkazy ve výsledku volají interní API pro přepnutí sítě
- změny stavu mohou současně spouštět i další integrace, například MQTT publikaci

## Založení bota

1. Otevři Telegram a najdi oficiálního bota BotFather (`@BotFather`).
2. Pošli mu příkaz `/newbot` a vytvoř bota dle jeho instrukcí.
3. BotFather ti vrátí HTTP API token ve tvaru `123456:ABC-DEF...`.

## Získání `chat id` a `thread id`

Nejjednodušší způsob je zavolat Telegram API `getUpdates` a vyhledat pole `chat.id` a (pokud používáš forum topics) `message_thread_id` v obdržených zprávách.

1. V prohlížeči nebo v `curl` zavolej:

	 https://api.telegram.org/bot<bot_token>/getUpdates

	 (místo `<bot_token>` vlož svůj bot token, např. `123456:ABC-DEF...`).

2. V odpovědi hledej v `result[*]` objekt `message` nebo `channel_post`. Příklad zkrácené odpovědi:

```
{
	"ok": true,
	"result": [
		{
			"update_id": 123456789,
			"message": {
				"message_id": 12,
				"chat": {
					"id": -1001234567890,
					"title": "Moje skupina",
					"type": "supergroup"
				},
				"message_thread_id": 56,
				"text": "/sit1"
			}
		}
	]
}
```

Poznámky:
- V soukromém chatu je `chat.id` kladné číslo, v kanálech a supergroups má často formát `-100...`.
- Pokud `getUpdates` nic nevrátí, pošli do bota zprávu nebo použij příkaz a zopakuj volání.