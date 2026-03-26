# AlbiDownloader

Nástroj stáhne seznam **BNL** souborů z oficiální stránky [Kouzelné čtení – soubory ke stažení](https://www.kouzelnecteni.cz/soubory-ke-stazeni), uloží manifest do CSV a volitelně soubory stáhne z hostitele `albidownload.eu`.

Stránka běží na Next.js a odkazy na `.bnl` v HTML při běžném `curl` nejsou — skript proto používá **Playwright (Chromium)** k načtení stránky jako v prohlížeči.

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
4. V interaktivním terminálu se **zeptá**, zda chceš soubory stáhnout a do **jaké složky** (výchozí je `./downloads`).
5. Při potvrzení stáhne soubory do zvolené složky.

### Užitečné přepínače

| Přepínač | Význam |
|----------|--------|
| `--download` | Stáhnout bez dotazů do složky z `--out` (vhodné pro skripty). |
| `--out SLOŽKA` | Cíl pro `.bnl` (výchozí `downloads`). |
| `--csv SOUBOR` | Jméno CSV manifestu (výchozí `albi_downloads.csv`). |
| `--no-interactive` | Jen CSV + přehled, žádné `input()` (např. v CI). |
| `--headed` | Zobrazí okno prohlížeče (ladění). |

**Příklad:** stáhnout vše bez dotazů do `~/AlbiBNL`:

```bash
python download.py --download --out ~/AlbiBNL
```

---

## Řešení problémů

- **„No .bnl entries found“** — zkontroluj síť; případně `python -m playwright install chromium` a znovu spusť, nebo vyzkoušej `--headed`.
- **Chyba importu `playwright`** — aktivuj `.venv` a znovu `pip install -r requirements.txt`.

---

## Licence / použití

Používej v souladu s podmínkami webu a jen pro osobní zálohování obsahu, ke kterému máš oprávnění. Tento projekt není oficiální produkt Albi.
