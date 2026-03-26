# AlbiDownloader

Nástroj stáhne seznam **BNL** souborů z oficiální stránky [Kouzelné čtení – soubory ke stažení](https://www.kouzelnecteni.cz/soubory-ke-stazeni), uloží manifest do CSV a volitelně soubory stáhne z hostitele `albidownload.eu`.

Stránka běží na Next.js a odkazy na `.bnl` v HTML při běžném `curl` nejsou — skript proto používá **Playwright (Chromium)** k načtení stránky jako v prohlížeči.

### Albi tužka — jedna kniha, jeden soubor

Podle [oficiálního návodu Jak nahrát audio soubor](https://www.kouzelnecteni.cz/co-je-kouzelne-cteni/jak-nahrat-audio-soubor) platí mimo jiné: **při aktualizaci nejdřív smaž z tužky původní soubor**, pak nahraj nový. **Dvě různé verze / dva podobné `.bnl` ke stejné knize** na kartě v tužce mohou způsobit, že kniha **nebude fungovat**. Některé tituly jsou navíc v **`.zip`** — před nahráním je musíš **rozbalit** a do tužky kopírovat až **`.bnl`**.

Skript po načtení seznamu **upozorní**, pokud:

- u **stejného názvu knihy** (po sjednocení mezer a uvozovek) jsou **více různých `.bnl` souborů**, nebo  
- **stejné číselné id** (z názvu souboru, např. přípona `_4043`) vystupuje u **více různých názvů souborů** — Albi nemá jednotné pojmenování, jde ale často o stejný produkt; na tužce má být jen jeden soubor.

Pokud je **stejný název `.bnl` souboru** v nabídce **víckrát** (jiná cesta ke stažení nebo jiný nadpis stránky), do výpisu i CSV se **uloží jen první výskyt** — nestahují se duplicitní kopie pod různými URL.

---

## Požadavky

- **Python 3.10+** (doporučeno 3.11 nebo 3.12)
- Připojení k internetu
- První spuštění: nainstalovaný **Chromium pro Playwright** (viz níže)

---

## Jednorázová instalace (Mac i Windows)

V kořeni projektu (složka s `download.py`):

```bash
python3 -m venv .venv
```

**macOS / Linux**

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

**Windows (PowerShell nebo CMD)**

```bat
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Příkaz `playwright install chromium` stáhne prohlížeč pro automatizaci — stačí **jednou** (nebo po přeinstalaci prostředí).

---

## Spuštění

### macOS / Linux

Aktivuj virtuální prostředí (pokud ještě není aktivní):

```bash
source .venv/bin/activate
python download.py
```

Nebo použij přiložený skript (vytvoří `.venv`, nainstaluje závislosti a spustí skript):

```bash
chmod +x run.sh
./run.sh
```

### Windows

V CMD nebo PowerShell z kořene projektu:

```bat
.venv\Scripts\activate
python download.py
```

Nebo dvojklik / z příkazové řádky:

```bat
run.bat
```

(`run.bat` aktivuje venv, doinstaluje závislosti a spustí `download.py`.)

---

## Co skript udělá

1. Načte stránku v Chromium, projde stránkování a vytáhne odkazy na `.bnl`.
2. Uloží **`albi_downloads.csv`** (manifest).
3. Vypíše **přehled nalezených položek**.
4. V interaktivním terminálu se **zeptá**, zda chceš soubory stáhnout a do **jaké složky** (výchozí je `./downloads`), případně na **další složky**, kde už `.bnl` máš (např. karta) — ty se při stahování přeskočí.
5. Při potvrzení stáhne **jen chybějící** soubory (předem vypíše plán: kolik z celkového počtu je třeba doplnit).

**Výchozí chování (bez `--no-skip-existing`):** nestahuje se nic, co už jako neprázdný soubor existuje v **`--out`**, nebo v dodaných složkách (**`--skip-if-present-in`**, proměnná **`ALBI_SKIP_IF_PRESENT_IN`**, soubor **`albi_skip_dirs.txt`** v kořeni projektu — jedna cesta na řádek, řádky začínající `#` se ignorují). Více cest v proměnné odděl `|`. Úplné znovustažení do `--out` vynutíš **`--no-skip-existing`**.

### Užitečné přepínače

| Přepínač | Význam |
|----------|--------|
| `--download` | Stáhnout do `--out`; s `--no-interactive` bez dotazů. V TTY se může zeptat na složky s už nahranými `.bnl`. |
| `--out SLOŽKA` | Cíl pro `.bnl` (výchozí `downloads`). |
| `--csv SOUBOR` | Jméno CSV manifestu (výchozí `albi_downloads.csv`). |
| `--no-interactive` | Jen CSV + přehled, žádné `input()` (např. v CI). |
| `--headed` | Zobrazí okno prohlížeče (ladění). |
| `--skip-if-present-in DIR` | Nestahovat soubor, pokud už existuje (nenulová velikost) v `DIR`. Opakováním přidáš další kořeny (např. záloha + připojená karta). |
| `--no-skip-existing` | Stáhnout znovu i když už stejný soubor leží v `--out`. |
| `--no-extra-skip-sources` | Ignorovat `ALBI_SKIP_IF_PRESENT_IN` a `albi_skip_dirs.txt` (jen CLI a interaktivní cesty). |

### Karta / SD — jen chybějící soubory do PC

Když už máš část `.bnl` na kartě (nebo v záloze) a chceš doplnit jen to, co v cílové složce na disku ještě není, předej **cestu ke kartě** (např. připojený svazek na Macu):

```bash
python download.py --download --out ~/AlbiBNL \
  --skip-if-present-in /Volumes/JMENO_KARTY
```

Nebo jednorázově v shellu (Mac/Linux):

```bash
export ALBI_SKIP_IF_PRESENT_IN="/Volumes/JMENO_KARTY"
python download.py --download --out ~/AlbiBNL
```

Skript nejdřív zkontroluje tyto složky: pokud tam stejnojmenný soubor už je a není prázdný, **nestahuje ho znovu**. Pak platí pravidlo pro `--out`: existující lokální kopie se také přeskakuje (pokud nepoužiješ `--no-skip-existing`). HTTP stahování proběhne jen pro řádky, které opravdu chybí — na konci uvidíš souhrn stažených vs. přeskočených.

---

## Řešení problémů

- **„No .bnl entries found“** — zkontroluj síť; případně `python -m playwright install chromium` a znovu spusť, nebo vyzkoušej `--headed`.
- **Chyba importu `playwright`** — aktivuj `.venv` a znovu `pip install -r requirements.txt`.

---

## Repozitář

Zdrojový kód: [github.com/pavelprokes/AlbiDownloader](https://github.com/pavelprokes/AlbiDownloader)

**Klíčová slova / témata (GitHub Topics):** na stránce repa v *Settings → General → Topics* můžeš doplnit např.  
`python`, `albi`, `kouzelne-cteni`, `bnl`, `downloader`, `playwright`, `web-scraping`, `czech`, `audio`, `audiobook` — přehled je také v souboru `pyproject.toml` u pole `keywords`.

S [GitHub CLI](https://cli.github.com/) (po `gh auth login`):

```bash
gh repo edit pavelprokes/AlbiDownloader --add-topic python --add-topic albi --add-topic kouzelne-cteni --add-topic bnl --add-topic downloader --add-topic playwright --add-topic web-scraping --add-topic czech --add-topic audio
```

```bash
git clone https://github.com/pavelprokes/AlbiDownloader.git
cd AlbiDownloader
```

---

## Licence / použití

Používej v souladu s podmínkami webu a jen pro osobní zálohování obsahu, ke kterému máš oprávnění. Tento projekt není oficiální produkt Albi.
