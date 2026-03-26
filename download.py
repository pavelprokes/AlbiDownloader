"""
Scrape Kouzelné čtení download page and optionally fetch .bnl files from albidownload.eu.
Requires Playwright (Chromium) because the site is a Next.js app without BNL URLs in the initial HTML.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from collections import defaultdict
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
ALBI_AUDIO_HELP_URL = (
    "https://www.kouzelnecteni.cz/co-je-kouzelne-cteni/jak-nahrat-audio-soubor"
)
SKIP_DIRS_ENV = "ALBI_SKIP_IF_PRESENT_IN"
SKIP_DIRS_FILENAME = "albi_skip_dirs.txt"


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*]', "_", name)


def _file_nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def load_skip_if_present_dirs(
    cli_paths: list[Path] | None,
    *,
    cwd: Path | None = None,
    use_env: bool = True,
    use_file: bool = True,
) -> list[Path]:
    """
    Merge skip-directory sources: CLI, then env ALBI_SKIP_IF_PRESENT_IN (| separated),
    then optional albi_skip_dirs.txt (one path per line, # comments).
    """
    cwd = cwd or Path.cwd()
    seen: set[str] = set()
    out: list[Path] = []

    def add(p: Path) -> None:
        p = p.expanduser()
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)

    for p in cli_paths or []:
        add(Path(p))

    if use_env:
        raw = os.environ.get(SKIP_DIRS_ENV, "").strip()
        if raw:
            for part in raw.split("|"):
                part = part.strip()
                if part:
                    add(Path(part))

    if use_file:
        fp = cwd / SKIP_DIRS_FILENAME
        if fp.is_file():
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                add(Path(line))

    return out


def merge_extra_skip_dirs(base: list[Path], *more: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for group in (base, *more):
        for p in group:
            p = p.expanduser()
            try:
                key = str(p.resolve())
            except OSError:
                key = str(p)
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out


def _norm_title(title: str) -> str:
    t = (title or "").strip().strip('"').strip("'")
    t = " ".join(t.lower().split())
    return t or "(untitled)"


def _norm_basename(filename: str) -> str:
    return Path(filename or "").name.lower()


def extract_product_id(filename: str) -> str | None:
    """
    Albi encodes a numeric id in many .bnl names: prefix '4064_...' or suffix '..._4043' / '..._4024-20250626-110400'.
    Same id + different base name can mean two packages for one product (problematic on the pen).
    """
    base = Path(filename).name.lower()
    if not base.endswith(".bnl"):
        return None
    stem = base[: -4]
    m = re.match(r"^(\d+)_", stem)
    if m:
        return m.group(1)
    m = re.search(r"_(\d+)(?:-\d{8}(?:-\d+)?)?$", stem)
    if m:
        return m.group(1)
    return None


def warn_duplicate_titles_for_pen(rows: list[dict[str, Any]]) -> None:
    """
    Albi docs: only one BNL per book on the pen; replace = delete the old file first.
    Warn if the listing contains the same book title with more than one distinct .bnl filename.
    """
    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_title[_norm_title(r.get("title") or "")].append(r)

    conflicts: list[tuple[str, list[dict[str, Any]]]] = []
    for key, group in by_title.items():
        names = {g.get("filename") or "" for g in group}
        names.discard("")
        if len(names) > 1:
            conflicts.append((key, group))

    if not conflicts:
        return

    print(
        "\nWARNING: The same book title is listed with more than one .bnl file. "
        "On the Albi pen only one audio package should exist per book — conflicting copies "
        "can stop the book from working. Before uploading a newer file, remove the old .bnl "
        f"from the pen. Official guide: {ALBI_AUDIO_HELP_URL}\n"
    )
    for _key, group in sorted(conflicts, key=lambda x: x[0]):
        display = (group[0].get("title") or "").strip() or "(untitled)"
        print(f"  Title: {display}")
        seen: set[str] = set()
        for r in group:
            fn = r.get("filename") or ""
            if fn in seen:
                continue
            seen.add(fn)
            ver = r.get("version") or ""
            print(f"    - {fn}  [{ver}]")
    print()


def warn_duplicate_product_ids_for_pen(rows: list[dict[str, Any]]) -> None:
    """Same numeric id in two different .bnl basenames — likely the same Albi product, different naming."""
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        pid = r.get("product_id") or extract_product_id(r.get("filename") or "")
        if not pid:
            continue
        by_id[pid].append(r)

    conflicts: list[tuple[str, list[dict[str, Any]]]] = []
    for pid, group in by_id.items():
        names = {g.get("filename") or "" for g in group}
        names.discard("")
        if len(names) > 1:
            conflicts.append((pid, group))

    if not conflicts:
        return

    print(
        "\nWARNING: The same numeric product id appears in more than one .bnl file name. "
        "Albi does not use one consistent file naming pattern — treat these as the same product family: "
        "only one .bnl should be on the pen. Remove the older file before replacing. "
        f"Guide: {ALBI_AUDIO_HELP_URL}\n"
    )
    for pid, group in sorted(conflicts, key=lambda x: x[0]):
        print(f"  Product id ~{pid}")
        seen: set[str] = set()
        for r in group:
            fn = r.get("filename") or ""
            if fn in seen:
                continue
            seen.add(fn)
            t = (r.get("title") or "").strip() or "(no title)"
            ver = r.get("version") or ""
            print(f"    - {fn}")
            print(f"      title: {t}  [{ver}]")
    print()


def print_pen_inconsistency_warnings(rows: list[dict[str, Any]]) -> None:
    warn_duplicate_titles_for_pen(rows)
    warn_duplicate_product_ids_for_pen(rows)


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
                "product_id": extract_product_id(name) or "",
                "bnl_url": bnl,
                "page": page_num,
                "variants_json": str(it.get("variants") or []),
            }
        )

    return rows


def scrape_all_pages(headless: bool, max_pages: int, delay_s: float) -> tuple[list[dict[str, Any]], int]:
    """
    Returns (rows, skipped_duplicate_basename_count).
    Same .bnl basename may appear twice with different URLs or card titles on the site — keep first only.
    """
    all_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_basenames: set[str] = set()
    skipped_duplicate_basename = 0
    page = 1
    while page <= max_pages:
        batch = scrape_page(page, headless=headless)
        if not batch:
            break
        new_count = 0
        for row in batch:
            u = row["bnl_url"]
            bn = _norm_basename(row.get("filename") or "")
            if u in seen_urls:
                continue
            if bn in seen_basenames:
                skipped_duplicate_basename += 1
                continue
            seen_urls.add(u)
            seen_basenames.add(bn)
            all_rows.append(row)
            new_count += 1
        if new_count == 0:
            break
        page += 1
        time.sleep(delay_s)
    return all_rows, skipped_duplicate_basename


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "title",
        "version",
        "size_label",
        "filename",
        "product_id",
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


def prompt_optional_skip_dirs() -> list[Path]:
    """Interactive: extra folders (e.g. SD card) where .bnl already exists — skip downloading those."""
    if not sys.stdin.isatty():
        return []
    try:
        raw = input(
            "Folders where you already have .bnl files (e.g. SD card), skip those — "
            "use | between paths, or Enter to skip [empty]: "
        ).strip()
    except EOFError:
        return []
    if not raw:
        return []
    return [Path(p.strip()).expanduser() for p in raw.split("|") if p.strip()]


def run_downloads(
    rows: list[dict[str, Any]],
    out_dir: Path,
    delay_s: float,
    skip_existing: bool,
    skip_if_present_in: list[Path] | None = None,
) -> tuple[int, int, int]:
    """
    Download BNL files. Returns (downloaded_ok, skipped_already_in_out, skipped_already_elsewhere).

    skip_if_present_in: extra roots (e.g. mounted SD card). If filename exists and is non-empty
    in any of these dirs, the HTTP download is skipped — useful when you already copied files to
    the card and only want missing titles in --out.
    """
    extra_roots = [p.expanduser().resolve() for p in (skip_if_present_in or [])]
    need: list[dict[str, Any]] = []
    skipped_out = 0
    skipped_elsewhere = 0
    for row in rows:
        name = row["filename"]
        safe = _safe_filename(name)
        dest = out_dir / safe
        present_elsewhere: Path | None = None
        for root in extra_roots:
            candidate = root / safe
            if _file_nonempty(candidate):
                present_elsewhere = root
                break
        if present_elsewhere is not None:
            skipped_elsewhere += 1
            print(f"  skip (already in {present_elsewhere}): {safe}")
            continue
        if skip_existing and _file_nonempty(dest):
            skipped_out += 1
            print(f"  skip (exists in --out): {safe}")
            continue
        need.append(row)

    n = len(rows)
    print(
        f"\nDownload plan: {len(need)} of {n} file(s) to fetch "
        f"(already have: {skipped_out} in --out, {skipped_elsewhere} under other folder(s))."
    )
    if not need:
        print("Nothing new to download.")
        return 0, skipped_out, skipped_elsewhere

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; AlbiDownloader/1.0; +local script; requests)"
            ),
            "Accept": "*/*",
        }
    )
    ok = 0
    for row in need:
        url = row["bnl_url"]
        name = row["filename"]
        safe = _safe_filename(name)
        dest = out_dir / safe
        print(f"  downloading: {safe}")
        try:
            download_file(url, dest, session)
            ok += 1
        except Exception as e:
            print(f"  ERROR {safe}: {e}", file=sys.stderr)
        time.sleep(delay_s)
    return ok, skipped_out, skipped_elsewhere


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Kouzelné čtení — list and download .bnl files. "
            "By default only missing .bnl files are downloaded: existing non-empty files in --out, "
            "in ALBI_SKIP_IF_PRESENT_IN / albi_skip_dirs.txt, and --skip-if-present-in are skipped. "
            "Use --no-skip-existing to re-download into --out."
        ),
    )
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
        help=(
            "Re-download every file into --out even when it already exists there (default is to skip those)"
        ),
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
    parser.add_argument(
        "--skip-if-present-in",
        action="append",
        default=None,
        metavar="DIR",
        help=(
            "If the .bnl already exists (non-empty) under DIR, skip downloading it. "
            "Repeat for multiple roots. Also see env ALBI_SKIP_IF_PRESENT_IN and file albi_skip_dirs.txt."
        ),
    )
    parser.add_argument(
        "--no-extra-skip-sources",
        action="store_true",
        help=(
            "Do not read ALBI_SKIP_IF_PRESENT_IN or albi_skip_dirs.txt (only --skip-if-present-in and "
            "interactive paths apply)"
        ),
    )
    args = parser.parse_args()

    headless = not args.headed
    print("Fetching listing (Chromium via Playwright)...")
    rows, skipped_dup_basename = scrape_all_pages(
        headless=headless, max_pages=args.max_pages, delay_s=args.delay
    )
    if skipped_dup_basename:
        print(
            f"Note: Skipped {skipped_dup_basename} duplicate listing(s) with the same .bnl file name "
            "but a different download URL or page title (kept the first occurrence)."
        )
    if not rows:
        print("No .bnl entries found. Try --headed to see the page, or run: python -m playwright install chromium")
        return 1

    write_csv(rows, args.csv)
    print(f"Wrote manifest: {args.csv.resolve()} ({len(rows)} rows)")

    print_findings_summary(rows)
    print_pen_inconsistency_warnings(rows)

    do_download = bool(args.download)
    out_dir = args.out

    interactive_skip: list[Path] = []
    if not args.download and not args.no_interactive and sys.stdin.isatty():
        do_download, out_dir = prompt_download_destination(args.out)
        if do_download:
            interactive_skip = prompt_optional_skip_dirs()
    elif args.download and not args.no_interactive and sys.stdin.isatty():
        interactive_skip = prompt_optional_skip_dirs()
    elif not args.download:
        print("Non-interactive mode: manifest only. Run with --download or answer prompts in a TTY.")

    if do_download:
        out_dir.mkdir(parents=True, exist_ok=True)
        use_ef = not args.no_extra_skip_sources
        extra = merge_extra_skip_dirs(
            load_skip_if_present_dirs(
                args.skip_if_present_in,
                use_env=use_ef,
                use_file=use_ef,
            ),
            interactive_skip,
        )
        if not args.no_skip_existing:
            print(
                "Default: only download .bnl files that are still missing (non-empty copies in --out "
                "or other configured folders are skipped)."
            )
        else:
            print("Re-downloading into --out even when files already exist (--no-skip-existing).")
        if extra:
            print(f"Also treating as already-owned (skip if file exists): {[str(p) for p in extra]}")
        print(f"Downloading into {out_dir.resolve()} ...")
        ok, sk_out, sk_else = run_downloads(
            rows,
            out_dir,
            delay_s=args.delay,
            skip_existing=not args.no_skip_existing,
            skip_if_present_in=extra,
        )
        print(
            f"Done. Downloaded: {ok}, skipped (already in --out): {sk_out}, "
            f"skipped (already on other path): {sk_else}"
        )
    elif not args.download and sys.stdin.isatty() and not args.no_interactive:
        print("Skipped download. Tip: run again with --download or answer 'y' when asked.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
