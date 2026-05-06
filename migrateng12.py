"""
NG12 CSS Image Migrator
=======================
Takes 24093_user.css (the live userstyles.world version) as input,
downloads every remaining web.archive.org image, saves them to the
`images/` folder in your local GitHub repo clone, and writes a new
NG12.user.css with ALL archive.org URLs replaced by your GitHub Pages URLs.

Nothing in the CSS is changed except the URLs. Line endings, spacing,
comments, @var blocks — everything else is preserved byte-for-byte.

Usage
-----
1. Clone your repo locally:
       git clone https://github.com/Kakuyamii/NG12-theme.git

2. Place 24093_user.css in the repo root (or adjust CSS_INPUT_FILE below).

3. Run this script from the repo root:
       pip install requests
       python migrate_ng12.py

4. In GitHub Desktop, commit and push everything.

5. Your updated CSS will be at NG12.user.css, referencing:
       https://kakuyamii.github.io/NG12-theme/images/<filename>
"""

import re
import os
import sys
import time
import hashlib
import requests
from pathlib import Path
from urllib.parse import urlparse

# ── Configuration ─────────────────────────────────────────────────────────────
CSS_INPUT_FILE    = "24093.user.css"   # The live version from userstyles.world
CSS_OUTPUT_FILE   = "NG12.user.css"   # Final output — ready to paste into Stylus
IMAGES_DIR        = "images"          # Folder committed to the repo
GITHUB_PAGES_BASE = "https://kakuyamii.github.io/NG12-theme"

DOWNLOAD_DELAY  = 0.4
REQUEST_TIMEOUT = 45
MAX_RETRIES     = 10
RETRY_DELAYS    = [5, 10, 20, 30, 45, 60, 90, 120, 180, 300]
LOG_FILE        = "migration_log.txt"
# ──────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NG12-migrator/1.0; "
        "+https://github.com/Kakuyamii/NG12-theme)"
    )
}


def extract_archive_urls(css):
    """Return every unique web.archive.org URL found inside url(...) in the CSS."""
    pattern = re.compile(
        r"""url\(\s*["']?(https?://web\.archive\.org/[^"'\)\s]+)["']?\s*\)""",
        re.IGNORECASE
    )
    return list(dict.fromkeys(pattern.findall(css)))  # unique, order-preserved


def original_filename_from_wayback(url):
    """
    Extract the original filename from a Wayback Machine URL.
    e.g. .../web/20120719011330im_/http://cssimg.ngfiles.com/bg-header/sitelinks.png
    -> sitelinks.png
    """
    m = re.search(r"web\.archive\.org/web/\d+[^/]*/https?://[^/]+(.+)", url)
    if m:
        path = m.group(1)
    else:
        path = urlparse(url).path
    return Path(path.split("?")[0]).name


def safe_filename(url, used):
    """
    Derive a filesystem-safe filename. Appends a short hash suffix only if
    two different URLs would produce the same filename.
    """
    basename = original_filename_from_wayback(url)

    if not basename or "." not in basename:
        basename = hashlib.md5(url.encode()).hexdigest()[:12] + ".bin"

    safe = re.sub(r"[^\w.\-]", "_", basename)

    if safe in used and used[safe] != url:
        stem, ext = os.path.splitext(safe)
        suffix = hashlib.md5(url.encode()).hexdigest()[:6]
        safe = f"{stem}_{suffix}{ext}"

    return safe


def download(url, dest, log):
    """
    Download url to dest. Retries up to MAX_RETRIES times with increasing delays.
    Returns True on success.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            if len(resp.content) == 0:
                raise ValueError("Server returned an empty body (0 bytes)")

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            msg = f"  OK  {dest.name}  ({len(resp.content):,} bytes)"
            print(msg)
            log.write(msg + "\n")
            return True

        except (requests.RequestException, ValueError, OSError) as exc:
            wait = RETRY_DELAYS[attempt - 1]
            if attempt < MAX_RETRIES:
                msg = (
                    f"  FAIL  attempt {attempt}/{MAX_RETRIES}: {exc}\n"
                    f"        waiting {wait}s before retry ..."
                )
                print(msg)
                log.write(msg + "\n")
                time.sleep(wait)
            else:
                msg = (
                    f"  FAIL  attempt {attempt}/{MAX_RETRIES}: {exc}\n"
                    f"  ALL {MAX_RETRIES} attempts exhausted for this URL."
                )
                print(msg)
                log.write(msg + "\n")

    return False


def main():
    css_path = Path(CSS_INPUT_FILE)
    if not css_path.exists():
        sys.exit(
            f"ERROR: Cannot find '{CSS_INPUT_FILE}'.\n"
            "Make sure 24093.user.css is in the same folder as this script."
        )

    images_dir = Path(IMAGES_DIR)
    images_dir.mkdir(exist_ok=True)

    # Read input as raw bytes then decode — this preserves \r\n line endings
    # which Stylus requires to parse the UserCSS metadata header correctly.
    raw_bytes = css_path.read_bytes()
    css = raw_bytes.decode("utf-8")

    urls = extract_archive_urls(css)
    print(f"Found {len(urls)} unique web.archive.org URL(s) in {CSS_INPUT_FILE}\n")

    name_map = {}        # filename -> original URL (for collision detection)
    replacement_map = {} # original URL -> new GitHub Pages URL
    failed = []

    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write(f"NG12 Migration — {len(urls)} archive.org URLs\n{'='*60}\n\n")

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            log.write(f"\n[{i}] {url}\n")

            filename = safe_filename(url, name_map)
            name_map[filename] = url

            dest = images_dir / filename
            github_url = f"{GITHUB_PAGES_BASE}/{IMAGES_DIR}/{filename}"

            if dest.exists():
                msg = "  SKIP  already downloaded"
                print(msg)
                log.write(msg + "\n")
                replacement_map[url] = github_url
                time.sleep(0.05)
                continue

            ok = download(url, dest, log)
            if ok:
                replacement_map[url] = github_url
            else:
                failed.append(url)
                replacement_map[url] = url  # leave original URL if download failed
                msg = "  WARN  kept original URL (download failed)"
                print(msg)
                log.write(msg + "\n")

            time.sleep(DOWNLOAD_DELAY)

        # ── Rewrite CSS ──────────────────────────────────────────────────────
        # Only archive.org URLs are replaced. Nothing else is touched.
        print("\nRewriting CSS URLs ...")
        log.write("\n" + "=" * 60 + "\nURL replacements:\n")

        updated_css = css
        for old_url, new_url in replacement_map.items():
            updated_css = updated_css.replace(old_url, new_url)
            log.write(f"  {old_url}\n  -> {new_url}\n\n")

        # Write output preserving the original \r\n line endings.
        # Stylus requires \r\n to correctly parse the UserCSS metadata header.
        Path(CSS_OUTPUT_FILE).write_bytes(updated_css.encode("utf-8"))

        # ── Sanity check: nothing else changed ───────────────────────────────
        original_lines = css.splitlines()
        updated_lines  = updated_css.splitlines()

        if len(original_lines) != len(updated_lines):
            print(
                f"\nWARNING: line count changed! "
                f"({len(original_lines)} -> {len(updated_lines)}) "
                f"Check the output carefully."
            )
        else:
            changed = sum(
                1 for a, b in zip(original_lines, updated_lines) if a != b
            )
            print(
                f"\nLine count unchanged ({len(original_lines)} lines). "
                f"{changed} line(s) had URL replacements."
            )

        # ── Summary ──────────────────────────────────────────────────────────
        success = len(urls) - len(failed)
        print(f"\n{'='*60}")
        print(f"Done!  {success}/{len(urls)} images downloaded.")
        print(f"  Output CSS -> {CSS_OUTPUT_FILE}")
        print(f"  Images     -> {IMAGES_DIR}/")
        print(f"  Log        -> {LOG_FILE}")

        if failed:
            print(
                f"\nWARNING: {len(failed)} URL(s) could not be downloaded after "
                f"{MAX_RETRIES} attempts. Original URLs kept in CSS for these.\n"
                f"Check {LOG_FILE} for details.\n"
            )
            for u in failed:
                print(f"   - {u}")

        remaining = len(re.findall(
            r'url\(["\']?https?://web\.archive\.org/', updated_css
        ))
        if remaining == 0:
            print("\nNo web.archive.org URLs remain in the output. Fully self-hosted!")
        else:
            print(
                f"\nWARNING: {remaining} web.archive.org URL(s) still remain "
                f"(these failed to download — see above)."
            )

        print(f"""
Next steps
----------
1. In GitHub Desktop you should see:
     images/            (new/updated folder with all downloaded files)
     {CSS_OUTPUT_FILE}
2. Commit with a message like "Add self-hosted images".
3. Push to GitHub.
4. Make sure GitHub Pages is enabled:
   Settings -> Pages -> Deploy from branch: main, folder: / (root)
5. Paste the contents of {CSS_OUTPUT_FILE} into Stylus.
   It should save without any errors.
""")

        log.write(
            f"\nResult: {success}/{len(urls)} downloaded, {len(failed)} failed.\n"
        )


if __name__ == "__main__":
    main()
