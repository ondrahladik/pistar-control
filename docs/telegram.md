# Telegram bot

[Zpět na přehled](./readme.md)

Telegram integrace funguje jako lehké dálkové ovládání nad stejným API, které používá webové rozhraní.

## Konfigurace 

Nastavení je v sekci `telegram` v `config/app.ini`:
- `enabled`: zapíná nebo vypíná Telegram bota
- `token`: HTTP API token pro přístup k Telegramu, získaný od BotFather
- `chat_id`: ID chatu, kam bot posílá zprávy a odkud přijímá příkazy
- `thread_id`: ID vlákna v rámci chatu, pokud používáš forum topics (je potřeba pro skupiny s vlákny, není potřeba pro soukromé zprávy a klasické skupiny)

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
- Bot jde využívat v přímých zprávách a v klasických skupinách; v těchto případech stačí zadat pouze `chat_id` (`thread_id` není nutné).
- Pokud se jedná o skupinu, která používá vlákna, je potřeba zadat `thread_id`.
- Pokud `getUpdates` nic nevrátí, pošli do bota zprávu nebo použij příkaz a zopakuj volání.
- Když tato aplikace již beží, tak není možné použít `getUpdates`, protože bot je přihlášen k odběru aktualizací. V tomto případě je potřeba dočasně zastavit tuto aplikaci, získat `chat_id` a `thread_id` a poté aplikaci znovu spustit.