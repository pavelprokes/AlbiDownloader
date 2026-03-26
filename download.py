"""
Scrape Kouzelné čtení download page and optionally fetch .bnl files from albidownload.eu.
Requires Playwright (Chromium) because the site is a Next.js app without BNL URLs in the initial HTML.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.kouzelnecteni.cz/soubory-ke-stazeni"
SITE_ORIGIN = "https://www.kouzelnecteni.cz"
BNL_HOST = "albidownload.eu"


def _abs_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return SITE_ORIGIN + url
    return url


def scrape_page(page_num: int, headless: bool) -> list[dict[str, Any]]:
    """Load one listing page in Chromium and return book rows."""
    url = f"{BASE_URL}?page={page_num}" if page_num > 1 else BASE_URL
    rows: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="cs-CZ",
        )
        pg = context.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            pg.wait_for_selector("a[href*='.bnl']", timeout=90_000)
        except Exception:
            browser.close()
            return []

        items = pg.evaluate(
            """() => {
            const cards = Array.from(document.querySelectorAll('.shadow-product'));
            return cards.map((card) => {
              const titleEl = card.querySelector('h3');
              const title = titleEl ? titleEl.innerText.trim() : '';
              const verEl = card.querySelector('p');
              const version = verEl ? verEl.innerText.trim() : '';
              const imgEl = card.querySelector('img.motive') || card.querySelector('img[src*="stages"]') || card.querySelector('img');
              let cover = imgEl ? (imgEl.currentSrc || imgEl.src || '') : '';
              const linkEl = card.querySelector('a[href*=".bnl"]');
              const bnlUrl = linkEl ? linkEl.href : '';
              const spans = Array.from(card.querySelectorAll('span'));
              const sizeSpan = spans.find((s) => /MB/i.test(s.textContent || ''));
              const sizeLabel = sizeSpan ? sizeSpan.textContent.trim() : '';
              const sel = card.querySelector('select');
              const variants = sel
                ? Array.from(sel.options).map((o) => ({ value: o.value, label: o.text.trim() }))
                : [];
              return { title, version, cover, bnlUrl, sizeLabel, variants };
            });
          }"""
        )

        browser.close()

    for it in items:
        cover = _abs_url(it.get("cover"))
        bnl = it.get("bnlUrl") or ""
        if not bnl or BNL_HOST not in bnl or not bnl.lower().endswith(".bnl"):
            continue
        name = urlparse(bnl).path.split("/")[-1] or "unknown.bnl"
        rows.append(
            {
                "title": it.get("title") or "",
                "version": it.get("version") or "",
                "size_label": it.get("sizeLabel") or "",
                "cover_url": cover or "",
                "filename": name,
                "bnl_url": bnl,
                "page": page_num,
                "variants_json": str(it.get("variants") or []),
            }
        )

    return rows


def scrape_all_pages(headless: bool, max_pages: int, delay_s: float) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    page = 1
    while page <= max_pages:
        batch = scrape_page(page, headless=headless)
        if not batch:
            break
        new_count = 0
        for row in batch:
            u = row["bnl_url"]
            if u not in seen_urls:
                seen_urls.add(u)
                all_rows.append(row)
                new_count += 1
        if new_count == 0:
            break
        page += 1
        time.sleep(delay_s)
    return all_rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "title",
        "version",
        "size_label",
        "filename",
        "bnl_url",
        "cover_url",
        "page",
        "variants_json",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def download_file(url: str, dest: Path, session: requests.Session) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def print_findings_summary(rows: list[dict[str, Any]]) -> None:
    """Print a human-readable list of scraped BNL entries."""
    n = len(rows)
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  Found {n} BNL file(s)")
    print(sep)
    for i, r in enumerate(rows, 1):
        title = (r.get("title") or "(no title)").replace("\n", " ")
        if len(title) > 64:
            title = title[:61] + "..."
        ver = r.get("version") or ""
        size = r.get("size_label") or ""
        fn = r.get("filename") or ""
        extra = " | ".join(x for x in (ver, size) if x)
        print(f"  {i:3}. {title}")
        if extra:
            print(f"       {extra}")
        print(f"       → {fn}")
    print(f"{sep}\n")


def prompt_download_destination(default_out: Path) -> tuple[bool, Path]:
    """
    Ask whether to download and where. Returns (do_download, directory).
    On EOF or non-interactive failure, returns (False, default_out).
    """
    try:
        ans = input("Download these .bnl files now? [y/N]: ").strip().lower()
    except EOFError:
        return False, default_out
    if ans not in ("y", "yes", "a", "ano"):
        return False, default_out
    try:
        raw = input(f"Destination folder [{default_out}]: ").strip()
    except EOFError:
        return True, default_out
    dest = Path(raw).expanduser() if raw else default_out
    return True, dest


def run_downloads(
    rows: list[dict[str, Any]],
    out_dir: Path,
    delay_s: float,
    skip_existing: bool,
) -> tuple[int, int]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; AlbiDownloader/1.0; +local script; requests)"
            ),
            "Accept": "*/*",
        }
    )
    ok, skipped = 0, 0
    for row in rows:
        url = row["bnl_url"]
        name = row["filename"]
        safe = re.sub(r'[<>:"/\\\\|?*]', "_", name)
        dest = out_dir / safe
        if skip_existing and dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            print(f"  skip (exists): {safe}")
            continue
        print(f"  downloading: {safe}")
        try:
            download_file(url, dest, session)
            ok += 1
        except Exception as e:
            print(f"  ERROR {safe}: {e}", file=sys.stderr)
        time.sleep(delay_s)
    return ok, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Kouzelné čtení — list and download .bnl files.")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download .bnl files into --out directory",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("downloads"),
        help="Output folder for .bnl files (default: ./downloads)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("albi_downloads.csv"),
        help="CSV manifest path (default: ./albi_downloads.csv)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=500,
        help="Safety cap for pagination (default: 500)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Delay between HTTP downloads and between page fetches (seconds)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download even if file already exists in --out",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (debug)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Do not prompt for download folder (use with --download for automation)",
    )
    args = parser.parse_args()

    headless = not args.headed
    print("Fetching listing (Chromium via Playwright)...")
    rows = scrape_all_pages(headless=headless, max_pages=args.max_pages, delay_s=args.delay)
    if not rows:
        print("No .bnl entries found. Try --headed to see the page, or run: python -m playwright install chromium")
        return 1

    write_csv(rows, args.csv)
    print(f"Wrote manifest: {args.csv.resolve()} ({len(rows)} rows)")

    print_findings_summary(rows)

    do_download = bool(args.download)
    out_dir = args.out

    if not args.download and not args.no_interactive and sys.stdin.isatty():
        do_download, out_dir = prompt_download_destination(args.out)
    elif not args.download:
        print("Non-interactive mode: manifest only. Run with --download or answer prompts in a TTY.")

    if do_download:
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Downloading into {out_dir.resolve()} ...")
        ok, sk = run_downloads(
            rows,
            out_dir,
            delay_s=args.delay,
            skip_existing=not args.no_skip_existing,
        )
        print(f"Done. Downloaded: {ok}, skipped: {sk}")
    elif not args.download and sys.stdin.isatty() and not args.no_interactive:
        print("Skipped download. Tip: run again with --download or answer 'y' when asked.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
