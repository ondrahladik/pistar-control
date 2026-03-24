# Instalace

K instalaci budeš potřebovat přístup k terminálu na svém Pi-Star zařízení, buď přes SSH klienta, nebo můžeš použít SSH terminál v prohlížeči přímo v Pi-Star webovém rozhraní.

SSH terminál v Pi-Star webovém rozhraní se nachází v sekci `Configuration` -> `Expert` -> [`SSH Access`](http://pi-star.local/admin/expert/ssh_access.php). Pak se stačí přihlásit, kliknout do terminálu pravým myšítkem a vybrat, `Paste from browser` a otevře se okno pro zadání příkazu. Do něj vlož jeden z příkazů níže a klikni na `OK`, a pak ještě stiskni Enter.

Výchozí uživatelské jméno a heslo pro Pi-Star či SSH:
- **Jméno**: `pi-star`
- **Heslo**: `raspberry`

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

Instalace trvá přibližně 4 minuty.

## Manuální instalace

> [!WARNING]   
> Manuální instalace je určena pro pokročilé uživatele, kteří chtějí přizpůsobit instalaci nebo nemohou použít automatické skripty.  
> Doporučujeme použít automatickou instalaci, pokud nejsi zkušený s Linuxem.

Pro manuální instalaci postupuj přibližně podle následujících kroků:

- Ověř, že běžíš jako root (sudo).
- Přepni filesystem do read-write režimu (`rpi-rw`).
- Nainstaluj potřebné systémové balíčky. V instalčním skriptu jsou použity tyto balíčky: iptables, iptables-persistent, netfilter-persistent, python3, python3-pip, git, Nejedná se jen o závislosti pro Pi-Star Control, ale i pro správu firewallu.
- Stáhni program z git repozitáře, například do `/opt/pistar-control`.
- Zkopíruj konfigurační soubory z config/*.sample souborů.
- Nainstaluj Python závislosti (install/requirements.txt).
- Vytvoř a spusť systemd službu pro Pi-Star Control.

## Po instalaci

Po úspěšné instalaci se služba automaticky spustí a bude běžet na pozadí. Můžeš ji spravovat pomocí systemd:

```bash
sudo systemctl start pistar-control
sudo systemctl stop pistar-control
sudo systemctl restart pistar-control
sudo systemctl status pistar-control
```

Sledovat logy služby můžeš pomocí:

```bash
sudo journalctl -u pistar-control -f
```

## Výchozí nastavení

- **API token**: `pistar`
- **Port aplikace**: `5000`
- **URL aplikace**: http://pi-star.local:5000


