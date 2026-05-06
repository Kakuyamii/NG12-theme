"""
NG12 CSS Image Migrator
=======================
Reads NG12.css, downloads every external image (Wayback Machine + other CDNs),
saves them to an `images/` folder inside your local GitHub repo clone, and
writes a new CSS file with all URLs pointing to your GitHub Pages site.

Usage
-----
1. Clone your repo locally:
       git clone https://github.com/Kakuyamii/NG12-theme.git

2. Copy NG12.css into the repo root (or adjust CSS_INPUT_FILE below).

3. Run this script from the repo root:
       pip install requests
       python migrate_ng12_images.py

4. In GitHub Desktop, commit and push everything.
   Make sure GitHub Pages is enabled (Settings → Pages → branch: main, folder: / (root)).

5. Your updated CSS will reference:
       https://kakuyamii.github.io/NG12-theme/images/<filename>
"""

import re
import os
import sys
import time
import hashlib
import mimetypes
import requests
from pathlib import Path
from urllib.parse import urlparse

# ── Configuration ─────────────────────────────────────────────────────────────
CSS_INPUT_FILE  = "NG12.css"          # Source CSS (relative to CWD or absolute)
CSS_OUTPUT_FILE = "NG12-updated.css"  # Rewritten CSS output
IMAGES_DIR      = "images"            # Folder that will be committed to the repo
GITHUB_PAGES_BASE = "https://kakuyamii.github.io/NG12-theme"

DOWNLOAD_DELAY  = 0.4   # seconds between requests (be polite to archive.org)
REQUEST_TIMEOUT = 45    # seconds per request (longer to handle slow archive.org)
MAX_RETRIES     = 10    # attempts per URL before giving up entirely
# Delay (seconds) before each retry attempt 1-10.
# Starts short, grows long to ride out server-side rate limits / hiccups.
RETRY_DELAYS    = [5, 10, 20, 30, 45, 60, 90, 120, 180, 300]
LOG_FILE        = "migration_log.txt"
# ──────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NG12-migrator/1.0; "
        "+https://github.com/Kakuyamii/NG12-theme)"
    )
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_urls(css: str) -> list[str]:
    """Return every unique http(s) URL found inside url(...) in the CSS."""
    # Matches: url("..."), url('...'), url(...)
    pattern = re.compile(
        r"""url\(\s*["']?(https?://[^"'\)\s]+)["']?\s*\)""",
        re.IGNORECASE
    )
    return list(dict.fromkeys(pattern.findall(css)))  # unique, order-preserved


def original_path_from_wayback(url: str) -> str:
    """
    Given a Wayback Machine URL like
      https://web.archive.org/web/20120719011330im_/http://cssimg.ngfiles.com/bg-header/sitelinks.png
    return the path portion of the original URL:
      /bg-header/sitelinks.png
    """
    m = re.search(r"web\.archive\.org/web/\d+[^/]*/https?://[^/]+(.+)", url)
    if m:
        return m.group(1)
    return urlparse(url).path


def safe_filename(url: str, used: dict[str, str]) -> str:
    """
    Derive a filesystem-safe filename from the URL.
    Keeps the original basename when unambiguous; appends a short hash suffix
    if another URL already claimed that name.
    """
    if "web.archive.org" in url:
        path = original_path_from_wayback(url)
    else:
        path = urlparse(url).path

    basename = Path(path).name
    # Strip any query string that snuck in
    basename = basename.split("?")[0]

    # Ensure we have something usable
    if not basename or "." not in basename:
        basename = hashlib.md5(url.encode()).hexdigest()[:12] + ".bin"

    # Sanitise: keep only safe characters
    safe = re.sub(r"[^\w.\-]", "_", basename)

    # Resolve name collision: two different URLs → same basename
    if safe in used and used[safe] != url:
        stem, ext = os.path.splitext(safe)
        suffix = hashlib.md5(url.encode()).hexdigest()[:6]
        safe = f"{stem}_{suffix}{ext}"

    return safe


def guess_extension(response: requests.Response, fallback: str) -> str:
    """
    If the downloaded file has no extension (or a wrong one), try to fix it
    from the Content-Type header.
    """
    ct = response.headers.get("Content-Type", "")
    ext_from_ct = mimetypes.guess_extension(ct.split(";")[0].strip())
    _, current_ext = os.path.splitext(fallback)
    if current_ext:
        return fallback          # already has an extension, trust it
    if ext_from_ct:
        return fallback + ext_from_ct
    return fallback


def download(url: str, dest: Path, log) -> bool:
    """
    Download *url* to *dest*.

    Tries up to MAX_RETRIES (10) times.  Between each failure the script waits
    an increasing amount of time (RETRY_DELAYS) so that temporary rate-limits,
    timeouts, and server hiccups are all ridden out.  The script will NOT move
    on until it either succeeds or exhausts every attempt.

    Returns True only on a clean, non-empty download.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            # Guard: reject obviously empty responses
            if len(resp.content) == 0:
                raise ValueError("Server returned an empty body (0 bytes)")

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            msg = f"  ✓  {dest.name}  ({len(resp.content):,} bytes)"
            print(msg)
            log.write(msg + "\n")
            return True

        except (requests.RequestException, ValueError, OSError) as exc:
            wait = RETRY_DELAYS[attempt - 1]   # index 0-9 maps to attempt 1-10
            if attempt < MAX_RETRIES:
                msg = (
                    f"  ✗  attempt {attempt}/{MAX_RETRIES} failed: {exc}\n"
                    f"     ↻  waiting {wait}s before retry …"
                )
                print(msg)
                log.write(msg + "\n")
                time.sleep(wait)
            else:
                # Final attempt also failed — report and surrender this URL
                msg = (
                    f"  ✗  attempt {attempt}/{MAX_RETRIES} failed: {exc}\n"
                    f"  ✗✗  ALL {MAX_RETRIES} attempts exhausted for this URL."
                )
                print(msg)
                log.write(msg + "\n")

    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    css_path = Path(CSS_INPUT_FILE)
    if not css_path.exists():
        sys.exit(f"ERROR: Cannot find '{CSS_INPUT_FILE}'. "
                 "Run this script from the same folder as your CSS file.")

    images_dir = Path(IMAGES_DIR)
    images_dir.mkdir(exist_ok=True)

    css = css_path.read_text(encoding="utf-8")
    urls = extract_urls(css)

    print(f"Found {len(urls)} unique external URL(s) in {CSS_INPUT_FILE}\n")

    # name_map : basename → original URL  (for collision detection)
    name_map: dict[str, str] = {}
    # replacement_map : original URL → new GitHub Pages URL
    replacement_map: dict[str, str] = {}

    failed: list[str] = []

    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write(f"NG12 Image Migration — {len(urls)} URLs\n{'='*60}\n\n")

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            log.write(f"\n[{i}] {url}\n")

            filename = safe_filename(url, name_map)
            name_map[filename] = url

            dest = images_dir / filename
            github_url = f"{GITHUB_PAGES_BASE}/{IMAGES_DIR}/{filename}"

            if dest.exists():
                msg = f"  ⏭  already downloaded — skipping"
                print(msg); log.write(msg + "\n")
                replacement_map[url] = github_url
                time.sleep(0.05)
                continue

            ok = download(url, dest, log)
            if ok:
                replacement_map[url] = github_url
            else:
                failed.append(url)
                replacement_map[url] = url   # leave original URL in CSS
                msg = f"  ⚠  kept original URL (download failed)"
                print(msg); log.write(msg + "\n")

            time.sleep(DOWNLOAD_DELAY)

        # ── Rewrite CSS ──────────────────────────────────────────────────────
        print("\nRewriting CSS URLs …")
        log.write("\n" + "="*60 + "\nURL replacements:\n")

        updated_css = css
        for old_url, new_url in replacement_map.items():
            # Replace the bare URL string wherever it appears
            # (handles quoted and unquoted url() forms)
            updated_css = updated_css.replace(old_url, new_url)
            log.write(f"  {old_url}\n  → {new_url}\n\n")

        Path(CSS_OUTPUT_FILE).write_text(updated_css, encoding="utf-8")

        # ── Summary ──────────────────────────────────────────────────────────
        success  = len(urls) - len(failed)
        print(f"\n{'='*60}")
        print(f"Done!  {success}/{len(urls)} images downloaded successfully.")
        print(f"  Updated CSS  → {CSS_OUTPUT_FILE}")
        print(f"  Images       → {IMAGES_DIR}/")
        print(f"  Full log     → {LOG_FILE}")

        if failed:
            print(
                f"\n⚠  {len(failed)} URL(s) could NOT be downloaded even after "
                f"{MAX_RETRIES} attempts each (original URLs kept in CSS).\n"
                f"   These may be permanently dead links on the Wayback Machine.\n"
                f"   Check {LOG_FILE} for full error details, then either:\n"
                f"     - supply the files manually to the images/ folder, or\n"
                f"     - search archive.org for an alternative snapshot.\n"
            )
            for u in failed:
                print(f"   - {u}")

        print(f"""
Next steps
----------
1. Rename {CSS_OUTPUT_FILE} → NG12.css (or whatever your userstyle manager expects).
2. In GitHub Desktop, you should see:
     • images/   (new folder with all the files)
     • NG12-updated.css
3. Commit with a message like "Add self-hosted images".
4. Push to GitHub.
5. Enable GitHub Pages in your repo Settings if not already done
   (Settings → Pages → Deploy from branch: main, folder: / (root)).
6. Your images will be live at:
   {GITHUB_PAGES_BASE}/{IMAGES_DIR}/<filename>
""")

        log.write(f"\nResult: {success}/{len(urls)} downloaded, "
                  f"{len(failed)} failed.\n")


if __name__ == "__main__":
    main()
