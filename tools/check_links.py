"""Check every external link in README.md and docs/*.md. Run manually (needs network and curl):

    python tools/check_links.py

arXiv links are looked up through the arXiv API, every other link must answer HTTP 200
(redirects followed). Exit code 1 if anything fails. Pages move: if a link breaks, search by title.
"""
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def collect():
    links = {}
    for md in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for _text, url in LINK.findall(md.read_text(encoding="utf-8")):
            links.setdefault(url, md.name)
    return links


def check_arxiv(ids):
    """IDs the arXiv API does not know, or None if the API cannot be reached (it rate-limits)."""
    api = "http://export.arxiv.org/api/query?max_results=200&id_list=" + ",".join(sorted(ids))
    for attempt in range(3):
        try:
            root = ET.fromstring(urllib.request.urlopen(api, timeout=60).read())
        except (urllib.error.URLError, TimeoutError):  # HTTPError (e.g. 429) is a URLError
            time.sleep(5 * (attempt + 1))
            continue
        ns = {"a": "http://www.w3.org/2005/Atom"}
        found = {e.find("a:id", ns).text.rsplit("/", 1)[1].split("v")[0] for e in root.findall("a:entry", ns)}
        return sorted(set(ids) - found)
    return None


def check_http(url, attempts=3):
    """True if the page answers 200. A failure is retried (with a pause) before it counts: sites rate-limit
    and networks blip, and a checker that reports false failures stops being trusted."""
    for attempt in range(attempts):
        r = subprocess.run(["curl", "-s", "-o", os.devnull, "-L", "-m", "45", "-w", "%{http_code}", "-A", "Mozilla/5.0", url],
                           capture_output=True, text=True)
        if r.stdout.strip() == "200":
            return True
        time.sleep(3 * (attempt + 1))
    return False


def main():
    links = collect()
    print(f"{len(links)} distinct external links")
    failures = []
    arxiv_ids = [u.rsplit("/", 1)[1] for u in links if "arxiv.org/abs/" in u]
    missing = check_arxiv(arxiv_ids) if arxiv_ids else []
    if missing is None:
        print("arXiv API unavailable, checking the arXiv pages over HTTP instead")
    else:
        failures += [(links[f"https://arxiv.org/abs/{i}"], f"arXiv:{i} not found") for i in missing]
    for url, md in links.items():
        if "arxiv.org/abs/" in url and missing is not None:
            continue
        if not check_http(url):
            failures.append((md, url))
    for md, what in failures:
        print(f"FAIL {md}: {what}")
    print("all links OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
