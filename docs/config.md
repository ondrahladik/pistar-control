# Konfigurace

Po úspěšné instalaci a prvním spuštění aplikace je potřeba provést základní nastavení, aby aplikace věděla, jaké profily přepínat. Konfigurace se nachází v souboru `config/app.ini`, který můžeš upravit buď přímo na zařízení, nebo pohodlně přes webové rozhraní.

## Základní nastavení

Pro základní funkčnost není potřeba nic měnit, ale doporučuji alespoň změnit výchozí API token pro lepší zabezpečení. Ten se používá pro autentizaci při přístupu k REST API a webovému rozhraní. Dále doporučuji si nastavit Aliasy pro dané profily, aby bylo jasné, který profil je který. Aliasy se zobrazují v přehledu a pomáhají rychle identifikovat aktivní profil. Například můžeš nastavit `Host 1` jako "BM" nebo "BrandMeister".

## Pokročilé nastavení

Pokročilé nastavení je více popsáno v jednotlivých stránkách dokumentace ([MQTT](mqtt.md) a [Telegram](telegram.md)).

`timezone`: časové pásmo, které aplikace používá pro dashboard, API, MQTT i Telegram. Časové pásmo je ve formátu IANA jako třeba `Europe/Prague`, pro systémový čas slouží `system`.

## Host profily

Jednou z klíčových funkcí aplikace je přepínání mezi dvěma host profily (`host1` a `host2`). Tyto profily jsou definovány v samostatných souborech, které se nachází ve složce `config/`. Díky tomu lze na jednom hotspotu snadno přepínat mezi dvěma různými nastaveními, například pro různé sítě. 

Při každém přepnutí dojde k přepsání hlavního host souboru (`/etc/mmdvmhost`) obsahem z vybraného profilu. To umožňuje rychlé a jednoduché přepínání bez nutnosti manuální editace host souboru.

Na stránce `/config` můžeš upravovat oba host profily ručně. Lepší je však si po jednom oba profily připravit přímo v Pi-Staru, odzkoušet jejich funkčnost a poté si stáhnout z Pi-Staru zálohu (http://pi-star.local/admin/config_backup.php). Ve stažené záloze najdeš soubor `mmdvmhost`, ten otevři třeba v poznámkovém bloku a zkopíruj celý jeho obsah do příslušného host profilu na stránce `/config`.

> [!IMPORTANT]  
> Při použití Pi-Star Control, nelze měnit nastavení přímo v Pi-Staru, ale vždy skrze tuto aplikaci.
