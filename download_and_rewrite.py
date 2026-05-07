"""
download_and_rewrite.py

Downloads every archive.org image referenced in 24093.user.css from the Wayback Machine.
Saves them mirroring the original ngfiles.com folder structure, organised by year:

    images/<year>/<original-ngfiles-path>
    e.g. images/2012/bg-skins/gold2-body.gif
         images/2013/bg-header/logo.png

Rewrites the CSS so every archive.org URL becomes:
    https://kakuyamii.github.io/NG12-theme/images/<year>/<original-ngfiles-path>

Usage:
    Place this script in the same folder as 24093.user.css, then run:
        python download_and_rewrite.py
"""

import re
import os
import time
import urllib.request
import urllib.error

# ── CONFIGURE THESE ────────────────────────────────────────────────────────────
INPUT_CSS   = "24093.user.css"
OUTPUT_CSS  = "24093.user.fixed.css"
IMAGES_DIR  = "images"
GITHUB_BASE = "https://kakuyamii.github.io/NG12-theme/images"  # no trailing slash
# ───────────────────────────────────────────────────────────────────────────────

# Retry cooldowns in seconds for attempts 1-9 (attempt 10 = final failure)
RETRY_DELAYS = [2, 4, 8, 15, 30, 60, 90, 120, 180]
MAX_RETRIES  = 10

# Matches: https://web.archive.org/web/<TIMESTAMP>[im_]/http[s]://cssimg.ngfiles.com/<path>
ARCHIVE_PATTERN = re.compile(
    r'(https://web\.archive\.org/web/(\d{4})\d+(?:im_)?/https?://cssimg\.ngfiles\.com/((?:[^/\s")]+/)*[^/\s")]+))'
)


def fetch_with_retry(url: str):
    """
    Attempt to download url up to MAX_RETRIES times with escalating cooldowns.
    Returns bytes on success, None if all attempts fail.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; archive-mirror-script)"}
            )
            with urllib.request.urlopen(req, timeout=45) as response:
                data = response.read()
            print(f"    OK ({len(data):,} bytes) on attempt {attempt}")
            return data

        except urllib.error.HTTPError as e:
            print(f"    Attempt {attempt}/{MAX_RETRIES} failed — HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            print(f"    Attempt {attempt}/{MAX_RETRIES} failed — URL error: {e.reason}")
        except TimeoutError:
            print(f"    Attempt {attempt}/{MAX_RETRIES} failed — Timed out")
        except Exception as e:
            print(f"    Attempt {attempt}/{MAX_RETRIES} failed — {type(e).__name__}: {e}")

        if attempt == MAX_RETRIES:
            print(f"    All {MAX_RETRIES} attempts failed. Skipping — original URL kept in CSS.")
            return None

        delay = RETRY_DELAYS[attempt - 1]
        print(f"    Waiting {delay}s before retry {attempt + 1}/{MAX_RETRIES}...")
        time.sleep(delay)

    return None


def main():
    if not os.path.isfile(INPUT_CSS):
        raise FileNotFoundError(
            f"Cannot find '{INPUT_CSS}' — make sure this script is in the "
            f"same folder as the CSS file."
        )

    with open(INPUT_CSS, "r", encoding="utf-8") as f:
        css = f.read()

    # Collect every unique archive URL, parsing year and original ngfiles path
    # { full_archive_url: (year, ngfiles_path) }
    url_info = {}
    for full_url, year, ngpath in ARCHIVE_PATTERN.findall(css):
        if full_url not in url_info:
            url_info[full_url] = (year, ngpath)

    total = len(url_info)
    print(f"Found {total} unique archive.org image URLs to process.\n")

    # Map: archive_url -> final github URL string, or None if download failed
    url_to_github = {}

    for i, (archive_url, (year, ngpath)) in enumerate(url_info.items(), 1):
        # local path:   images/2012/bg-skins/gold2-body.gif
        # github path:  https://kakuyamii.github.io/.../images/2012/bg-skins/gold2-body.gif
        path_parts = ngpath.replace("\\", "/").split("/")
        local_path  = os.path.join(IMAGES_DIR, year, *path_parts)
        github_url  = f"{GITHUB_BASE}/{year}/{ngpath}"

        print(f"[{i}/{total}] {archive_url}")
        print(f"  -> {local_path}")

        # Already downloaded in a previous run — skip
        if os.path.isfile(local_path):
            print(f"  Already on disk, skipping.")
            url_to_github[archive_url] = github_url
            continue

        data = fetch_with_retry(archive_url)

        if data is None:
            url_to_github[archive_url] = None
        else:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(data)
            print(f"  Saved.")
            url_to_github[archive_url] = github_url

        if i < total:
            time.sleep(1.5)
        print()

    # Rewrite CSS — replace each matched archive URL with its github equivalent
    def replacer(match):
        full_url = match.group(1)
        github = url_to_github.get(full_url)
        return github if github is not None else full_url

    new_css = ARCHIVE_PATTERN.sub(replacer, css)

    with open(OUTPUT_CSS, "wb") as f:
        f.write(new_css.encode("utf-8"))

    failed    = [u for u, g in url_to_github.items() if g is None]
    succeeded = total - len(failed)

    print("=" * 60)
    print(f"Done. {succeeded}/{total} images downloaded successfully.")
    print(f"CSS written to:  {OUTPUT_CSS}")
    print(f"Images saved in: {IMAGES_DIR}/")
    print()
    print(f"Push the entire '{IMAGES_DIR}/' folder to your GitHub repo,")
    print(f"then install '{OUTPUT_CSS}' as your userstyle.")

    if failed:
        print(f"\nWARNING: {len(failed)} URL(s) failed all retries (original URL kept in CSS):")
        for u in failed:
            print(f"  {u}")


if __name__ == "__main__":
    main()
