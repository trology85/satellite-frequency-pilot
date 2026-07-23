import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "satbeams_satellites.json").read_text(encoding="utf-8"))
RAW_DIR = ROOT / "raw" / "satbeams"
REPORTS_DIR = ROOT / "reports"
RAW_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.satbeams.com/api/v1/channels"
LIMIT = 100
MAX_PAGES = 200
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SatelliteFrequencyPilot/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.satbeams.com/channels",
}


def channel_count(transponders):
    return sum(len(tp.get("channels") or []) for tp in transponders)


def merge_page(target, page_transponders):
    for tp in page_transponders:
        tp_id = str(tp.get("id") or "")
        if not tp_id:
            continue
        existing = target.setdefault(tp_id, {**tp, "channels": []})
        known = {str(ch.get("id")) for ch in existing.get("channels", []) if ch.get("id") is not None}
        for ch in tp.get("channels") or []:
            ch_id = str(ch.get("id")) if ch.get("id") is not None else ""
            if ch_id and ch_id in known:
                continue
            existing.setdefault("channels", []).append(ch)
            if ch_id:
                known.add(ch_id)


session = requests.Session()
report = {
    "run_utc": datetime.now(timezone.utc).isoformat(),
    "source": "Satbeams API",
    "ok": True,
    "satellites": [],
}

for sat in CONFIG:
    item = {"id": sat["id"], "position": sat["position"], "ok": False, "errors": []}
    merged = {}
    offset = 0
    page_count = 0
    raw_channel_rows = 0
    try:
        while page_count < MAX_PAGES:
            params = {
                "sort": "freq",
                "dir": "asc",
                "position": sat["position"],
                "limit": LIMIT,
                "offset": offset,
            }
            response = session.get(BASE_URL, params=params, headers=HEADERS, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != 0:
                raise RuntimeError(f"API status={payload.get('status')}")
            data = payload.get("data") or {}
            page_transponders = data.get("transponders") or []
            rows = channel_count(page_transponders)
            page_count += 1
            raw_channel_rows += rows
            merge_page(merged, page_transponders)

            if rows == 0:
                break
            offset += LIMIT
            if rows < LIMIT:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(f"Sayfalama güvenlik sınırına ulaştı: {MAX_PAGES}")

        transponders = list(merged.values())
        unique_channels = channel_count(transponders)
        raw_payload = {
            "status": 0,
            "data": {
                "position": {"rounded_pos": sat["position"], "label": sat["position_label"]},
                "transponders": transponders,
            },
            "fetch_meta": {
                "fetched_utc": datetime.now(timezone.utc).isoformat(),
                "pages": page_count,
                "limit": LIMIT,
                "raw_channel_rows": raw_channel_rows,
                "unique_channels": unique_channels,
            },
        }
        raw_path = RAW_DIR / f"{sat['id']}.json"
        raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        item.update({
            "ok": bool(transponders and unique_channels),
            "pages": page_count,
            "transponders": len(transponders),
            "channels": unique_channels,
            "raw_channel_rows": raw_channel_rows,
            "raw_file": str(raw_path.relative_to(ROOT)),
        })
        if not item["ok"]:
            item["errors"].append("API boş veri döndürdü")
    except Exception as exc:
        item["errors"].append(f"{type(exc).__name__}: {exc}")
    report["satellites"].append(item)
    report["ok"] = report["ok"] and item["ok"]

(REPORTS_DIR / "satbeams_fetch_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
if not report["ok"]:
    raise SystemExit("Satbeams indirme başarısız")
