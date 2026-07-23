#!/usr/bin/env python3
"""KingOfSat Astra 19.2E erişim ve HTML yapı smoke testi.

Bu betik yalnızca sayfayı indirir, temel HTML göstergelerini sayar ve rapor üretir.
JSON kanal çıktısı üretmez; repodaki mevcut LyngSat akışına dokunmaz.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw" / "kingofsat-smoke"
REPORTS_DIR = ROOT / "reports"
DEFAULT_URL = "https://tr.kingofsat.net/pos-19.2E"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KingOfSat Astra 19.2E smoke testi")
    parser.add_argument("--url", default=DEFAULT_URL, help="Test edilecek KingOfSat URL'si")
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Ağ isteği yerine yerel HTML/TXT dosyasını test et",
    )
    return parser.parse_args()


def download(url: str) -> tuple[int, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = int(response.status)
            final_url = response.geturl()
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read()
            try:
                html = raw.decode(charset, errors="replace")
            except LookupError:
                html = raw.decode("utf-8", errors="replace")
            return status, final_url, html
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), exc.geturl(), body


def inspect_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    frequency_tables = soup.select("table.frequencies-table")
    frequency_rows = soup.select("table.frequencies-table tr[data-frequency-id]")
    channel_rows = soup.select("tr[data-channel-id]")
    non_empty_channel_rows = [
        row for row in channel_rows if (row.get("data-channel-id") or "").strip()
    ]
    feed_rows = soup.select("tr.feedblock, tr:has(td.feed)")

    heading_text = " ".join(
        element.get_text(" ", strip=True) for element in soup.select("h1, h4")
    )
    record_match = re.search(r"(\d[\d.]*)\s*Kayıt", heading_text, flags=re.IGNORECASE)
    advertised_records = None
    if record_match:
        advertised_records = int(record_match.group(1).replace(".", ""))

    block_markers = (
        "just a moment",
        "attention required",
        "captcha",
        "access denied",
        "cf-chl-",
    )
    lowered = html.lower()
    detected_block_markers = [marker for marker in block_markers if marker in lowered]

    return {
        "title": title,
        "bytes": len(html.encode("utf-8")),
        "frequency_table_count": len(frequency_tables),
        "frequency_row_count": len(frequency_rows),
        "channel_row_count": len(channel_rows),
        "non_empty_channel_id_count": len(non_empty_channel_rows),
        "feed_marker_count": len(feed_rows),
        "advertised_record_count": advertised_records,
        "block_markers": detected_block_markers,
    }


def validate(status: int, metrics: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if status != 200:
        errors.append(f"HTTP durum kodu 200 değil: {status}")
    if metrics["block_markers"]:
        errors.append("Engelleme/CAPTCHA göstergesi bulundu: " + ", ".join(metrics["block_markers"]))
    if metrics["bytes"] < 100_000:
        errors.append(f"HTML beklenenden küçük: {metrics['bytes']} bayt")
    if metrics["frequency_row_count"] < 20:
        errors.append(
            "Yeterli frekans satırı bulunamadı: "
            f"{metrics['frequency_row_count']} (minimum 20)"
        )
    if metrics["channel_row_count"] < 100:
        errors.append(
            "Yeterli kanal satırı bulunamadı: "
            f"{metrics['channel_row_count']} (minimum 100)"
        )
    title = str(metrics["title"]).lower()
    if "kingofsat" not in title or "19.2" not in title:
        errors.append(f"Beklenen Astra 19.2E KingOfSat başlığı bulunamadı: {metrics['title']!r}")
    return errors


def main() -> int:
    args = parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    source = "network"
    requested_url = args.url
    final_url = args.url

    if args.input_file:
        source = "local-file"
        requested_url = str(args.input_file)
        final_url = requested_url
        html = args.input_file.read_text(encoding="utf-8", errors="replace")
        status = 200
    else:
        status, final_url, html = download(args.url)

    metrics = inspect_html(html)
    errors = validate(status, metrics)
    ok = not errors

    raw_path = RAW_DIR / "astra-19.2e.html"
    raw_path.write_text(html, encoding="utf-8")

    report = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "test": "kingofsat-astra-19.2e-smoke",
        "source": source,
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "ok": ok,
        **metrics,
        "raw_file": str(raw_path.relative_to(ROOT)),
        "errors": errors,
    }

    report_path = REPORTS_DIR / "kingofsat_smoke_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not ok:
        print(f"Smoke test başarısız. Rapor: {report_path}", file=sys.stderr)
        return 1

    print(f"Smoke test başarılı. Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
