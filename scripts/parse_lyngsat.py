import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "satellites.json"
RAW = ROOT / "raw"
OUTPUT = ROOT / "output"
REPORTS = ROOT / "reports"

FREQ_RE = re.compile(r"(?<!\d)(\d{4,5}(?:\.\d+)?)\s*([HVLR])\b", re.I)
DATE_RE = re.compile(r"last updated\s+(\d{4}-\d{2}-\d{2})", re.I)
INT_RE = re.compile(r"\d+")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def direct_text(cell: Tag) -> str:
    return clean(cell.get_text(" ", strip=True))


def expand_table(table: Tag) -> list[list[Tag | None]]:
    rows: list[list[Tag | None]] = []
    spans: dict[int, tuple[Tag, int]] = {}
    for tr in table.find_all("tr", recursive=False):
        cells = tr.find_all(["td", "th"], recursive=False)
        row: list[Tag | None] = []
        col = 0
        idx = 0
        while idx < len(cells) or spans:
            if col in spans:
                cell, remaining = spans[col]
                row.append(cell)
                if remaining <= 1:
                    del spans[col]
                else:
                    spans[col] = (cell, remaining - 1)
                col += 1
                continue
            if idx >= len(cells):
                next_cols = [c for c in spans if c >= col]
                if not next_cols:
                    break
                while col < min(next_cols):
                    row.append(None)
                    col += 1
                continue
            cell = cells[idx]
            idx += 1
            rowspan = int(cell.get("rowspan", 1) or 1)
            colspan = int(cell.get("colspan", 1) or 1)
            for _ in range(colspan):
                row.append(cell)
                if rowspan > 1:
                    spans[col] = (cell, rowspan - 1)
                col += 1
        rows.append(row)
    return rows


def table_is_frequency_table(table: Tag) -> bool:
    text = clean(table.get_text(" ", strip=True))
    return "Frequency" in text and "Channel Name" in text and "VPID" in text


def infer_spacecraft(cell: Tag | None, fallback: str) -> str:
    if not cell:
        return fallback
    for a in cell.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/(?:muxes|maps/footprints)/([^_/]+(?:-[^_/]+)*)[_-](?:East|West|Europe|Wide|Ku|C|\d)", href)
        if m:
            return m.group(1).replace("-", " ")
    return fallback


def parse_system(text: str) -> dict[str, str | int]:
    parts = [clean(x) for x in re.split(r"\s+", text) if clean(x)]
    system = next((p for p in parts if p.startswith("DVB-") or p in {"DSS", "S2X"}), "")
    modulation = next((p for p in parts if p.upper() in {"QPSK", "8PSK", "16APSK", "32APSK"}), "")
    fec = next((p for p in parts if re.fullmatch(r"\d+/\d+", p)), "")
    nums = [int(p) for p in parts if p.isdigit()]
    sr = max(nums) if nums else 0
    return {"system": system, "modulation": modulation, "symbol_rate": sr, "fec": fec}


def first_channel_link(cell: Tag | None) -> tuple[str, str, str]:
    if not cell:
        return "", "", ""
    for a in cell.find_all("a", href=True):
        href = a["href"]
        if "/tvchannels/" in href:
            return clean(a.get_text(" ", strip=True)), "TV", href
        if "/radiochannels/" in href:
            return clean(a.get_text(" ", strip=True)), "RADIO", href
    return "", "", ""


def parse_one(sat: dict[str, str]) -> dict[str, Any]:
    path = RAW / f"{sat['id']}.html"
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    dm = DATE_RE.search(page_text)
    source_updated = dm.group(1) if dm else ""

    channels: list[dict[str, Any]] = []
    transponders: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    for table in soup.find_all("table"):
        if not table_is_frequency_table(table):
            continue
        for row in expand_table(table):
            if len(row) < 9:
                continue
            freq_text = direct_text(row[0]) if row[0] else ""
            fm = FREQ_RE.search(freq_text)
            if not fm:
                continue
            frequency = float(fm.group(1))
            if frequency.is_integer():
                frequency = int(frequency)
            polarization = fm.group(2).upper()
            sys_info = parse_system(direct_text(row[1]) if row[1] else "")
            name, channel_type, channel_url = first_channel_link(row[3] if len(row) > 3 else None)
            if not name:
                continue

            sid_text = direct_text(row[2]) if len(row) > 2 and row[2] else ""
            sid_match = INT_RE.search(sid_text.replace("*", ""))
            sid = int(sid_match.group()) if sid_match else None
            format_text = direct_text(row[5]) if len(row) > 5 and row[5] else ""
            vpid_text = direct_text(row[6]) if len(row) > 6 and row[6] else ""
            audio_text = direct_text(row[7]) if len(row) > 7 and row[7] else ""
            encryption = direct_text(row[8]) if len(row) > 8 and row[8] else ""
            spacecraft = infer_spacecraft(row[0], sat["name"])
            tp_id = f"{sat['id']}:{frequency}:{polarization}:{sys_info['symbol_rate']}"
            key = f"{tp_id}:{sid}:{name.casefold()}"
            if key in seen:
                continue
            seen.add(key)

            channel = {
                "name": name,
                "type": channel_type,
                "satellite_group": sat["name"],
                "spacecraft": spacecraft,
                "position": sat["position"],
                "frequency": frequency,
                "polarization": polarization,
                "symbol_rate": sys_info["symbol_rate"],
                "fec": sys_info["fec"],
                "system": sys_info["system"],
                "modulation": sys_info["modulation"],
                "sid": sid,
                "format": format_text,
                "vpid": vpid_text,
                "audio": audio_text,
                "encryption": encryption,
                "channel_url": channel_url,
                "tp_id": tp_id,
            }
            channels.append(channel)
            tp = transponders.setdefault(tp_id, {
                "tp_id": tp_id,
                "satellite_group": sat["name"],
                "spacecraft": spacecraft,
                "position": sat["position"],
                "frequency": frequency,
                "polarization": polarization,
                "symbol_rate": sys_info["symbol_rate"],
                "fec": sys_info["fec"],
                "system": sys_info["system"],
                "modulation": sys_info["modulation"],
                "channel_count": 0,
                "tv_count": 0,
                "radio_count": 0,
            })
            tp["channel_count"] += 1
            tp["radio_count" if channel_type == "RADIO" else "tv_count"] += 1

    channels.sort(key=lambda x: (float(x["frequency"]), x["polarization"], x["name"].casefold()))
    tp_list = sorted(transponders.values(), key=lambda x: (float(x["frequency"]), x["polarization"]))
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"name": "LyngSat", "url": sat["url"], "last_updated": source_updated},
        "satellite": {"id": sat["id"], "name": sat["name"], "position": sat["position"]},
        "counts": {"transponders": len(tp_list), "channels": len(channels), "tv": sum(c["type"] == "TV" for c in channels), "radio": sum(c["type"] == "RADIO" for c in channels)},
        "transponders": tp_list,
        "channels": channels,
    }


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    sats = json.loads(CONFIG.read_text(encoding="utf-8"))
    summary = {"generated_utc": datetime.now(timezone.utc).isoformat(), "satellites": []}
    combined_channels = []
    combined_tps = []
    for sat in sats:
        result = parse_one(sat)
        (OUTPUT / f"{sat['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["satellites"].append({"id": sat["id"], **result["counts"], "source_updated": result["source"]["last_updated"]})
        combined_channels.extend(result["channels"])
        combined_tps.extend(result["transponders"])
    combined = {"schema_version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(), "satellites": summary["satellites"], "transponders": combined_tps, "channels": combined_channels}
    (OUTPUT / "satellite_database.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "parse_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
