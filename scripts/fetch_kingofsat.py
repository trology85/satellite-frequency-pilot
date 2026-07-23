import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "kingofsat_satellites.json"
RAW = ROOT / "raw" / "kingofsat"
REPORTS = ROOT / "reports"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BLOCK_MARKERS = (
    "just a moment",
    "verify you are human",
    "captcha",
    "cf-chl-",
    "access denied",
)


def count_frequency_rows(html: str, soup: BeautifulSoup) -> int:
    count = len(soup.select("tr[data-frequency-id]"))
    if count == 0:
        count = len(re.findall(r"<tr\b[^>]*\bdata-frequency-id\s*=", html, re.I))
    return count


def fetch(url: str) -> tuple[int, str, str]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.7,en;q=0.6",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=60) as response:
        status = int(getattr(response, "status", 200))
        final_url = response.geturl()
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return status, final_url, raw.decode(charset, errors="replace")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    satellites = json.loads(CONFIG.read_text(encoding="utf-8"))
    report = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "source": "KingOfSat",
        "ok": True,
        "satellites": [],
    }

    for index, sat in enumerate(satellites):
        item = {"id": sat["id"], "url": sat["url"], "ok": False}
        try:
            status, final_url, html = fetch(sat["url"])
            path = RAW / f"{sat['id']}.html"
            path.write_text(html, encoding="utf-8")
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            lowered = html.casefold()
            block_markers = [marker for marker in BLOCK_MARKERS if marker in lowered]
            frequency_rows = count_frequency_rows(html, soup)
            channel_rows = len(soup.select("tr[data-channel-id]"))
            advertised = None
            m = re.search(r"(\d+)\s+Kayıt", soup.get_text(" ", strip=True), re.I)
            if m:
                advertised = int(m.group(1))

            item.update(
                {
                    "status": status,
                    "final_url": final_url,
                    "title": title,
                    "bytes": len(html.encode("utf-8")),
                    "frequency_rows": frequency_rows,
                    "channel_rows": channel_rows,
                    "advertised_records": advertised,
                    "block_markers": block_markers,
                    "raw_file": str(path.relative_to(ROOT)),
                }
            )
            errors = []
            if status != 200:
                errors.append(f"HTTP {status}")
            if block_markers:
                errors.append("Engelleme/CAPTCHA göstergesi bulundu")
            if frequency_rows < 5:
                errors.append(f"Frekans satırı çok az: {frequency_rows}")
            if channel_rows < 10:
                errors.append(f"Servis satırı çok az: {channel_rows}")
            item["errors"] = errors
            item["ok"] = not errors
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            item["errors"] = [f"{type(exc).__name__}: {exc}"]
        except Exception as exc:
            item["errors"] = [f"{type(exc).__name__}: {exc}"]

        report["satellites"].append(item)
        report["ok"] = report["ok"] and item["ok"]
        if index + 1 < len(satellites):
            time.sleep(2)

    report_path = REPORTS / "kingofsat_fetch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(f"KingOfSat indirme başarısız. Rapor: {report_path}")


if __name__ == "__main__":
    main()
