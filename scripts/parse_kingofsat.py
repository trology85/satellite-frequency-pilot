import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "kingofsat_satellites.json"
RAW = ROOT / "raw" / "kingofsat"
OUTPUT = ROOT / "output"
REPORTS = ROOT / "reports"

PAGE_DATE_RE = re.compile(r"en son guncelleme:\s*(\d{4}-\d{2}-\d{2})", re.I)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
INT_RE = re.compile(r"\d+")
TEST_NAME_RE = re.compile(r"^(?:test(?:\s|$)|tests?(?:\s|$)|portada$|gu[ií]a$)", re.I)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def lines(cell: Tag | None) -> list[str]:
    if not cell:
        return []
    return [clean(x) for x in cell.stripped_strings if clean(x)]


def direct_cells(row: Tag) -> list[Tag]:
    return row.find_all("td", recursive=False)


def first_number(text: str) -> str:
    m = NUMBER_RE.search(text)
    return m.group(0) if m else ""


def parse_frequency_row(row: Tag, sat: dict[str, str]) -> dict[str, Any] | None:
    cells = direct_cells(row)
    if len(cells) < 12:
        return None
    freq = first_number(clean(cells[2].get_text(" ", strip=True)))
    if not freq:
        return None
    frequency: int | float = float(freq)
    if frequency.is_integer():
        frequency = int(frequency)
    sr_fec = lines(cells[8])
    symbol_rate = int(sr_fec[0]) if sr_fec and sr_fec[0].isdigit() else 0
    fec = next((x for x in sr_fec[1:] if re.fullmatch(r"\d+/\d+", x)), "")
    satellite_link = cells[1].find("a", class_="bld")
    satellite_name = clean(satellite_link.get_text(" ", strip=True)) if satellite_link else clean(cells[1].get_text(" ", strip=True))
    tp_number = clean(cells[4].get_text(" ", strip=True))
    network = clean(cells[9].get_text(" ", strip=True))
    return {
        "tp_id": f"{sat['id']}:{frequency}:{clean(cells[3].get_text(' ', strip=True)).upper()}:{symbol_rate}",
        "satellite_group": sat["name"],
        "spacecraft": satellite_name or sat["name"],
        "position": sat["position"],
        "frequency": frequency,
        "polarization": clean(cells[3].get_text(" ", strip=True)).upper(),
        "transponder": tp_number,
        "beam": clean(cells[5].get_text(" ", strip=True)),
        "system": clean(cells[6].get_text(" ", strip=True)),
        "modulation": clean(cells[7].get_text(" ", strip=True)),
        "symbol_rate": symbol_rate,
        "fec": fec,
        "network": network,
        "nid": clean(cells[10].get_text(" ", strip=True)),
        "tid": clean(cells[11].get_text(" ", strip=True)),
        "channel_count": 0,
        "tv_count": 0,
        "radio_count": 0,
    }


def classify_channel(row: Tag) -> str:
    cells = direct_cells(row)
    if not cells:
        return ""
    classes = set(cells[0].get("class", []))
    if "v" in classes:
        return "TV"
    if "r" in classes:
        return "RADIO"
    return ""


def channel_name(cell: Tag) -> str:
    anchor = cell.find("a", class_="A3")
    if anchor:
        return clean(anchor.get_text(" ", strip=True))
    return clean(cell.get_text(" ", strip=True))


def parse_channel_row(row: Tag, tp: dict[str, Any]) -> dict[str, Any] | None:
    kind = classify_channel(row)
    if not kind:
        return None
    cells = direct_cells(row)
    if len(cells) < 14:
        return None
    name = channel_name(cells[2])
    if not name or TEST_NAME_RE.search(name):
        return None
    sid_text = clean(cells[7].get_text(" ", strip=True))
    sid_match = INT_RE.search(sid_text)
    if not sid_match:
        return None
    sid = int(sid_match.group())
    encryption_lines = lines(cells[6])
    encryption = " / ".join(encryption_lines)
    free_to_air = any(x.casefold() in {"sifresiz", "clear", "fta"} for x in encryption_lines)
    video_lines = lines(cells[8])
    audio_lines = lines(cells[9])
    updated_text = clean(cells[13].get_text(" ", strip=True))
    updated_match = re.search(r"\d{4}-\d{2}-\d{2}", updated_text)
    updated = updated_match.group(0) if updated_match else ""
    data_channel_id = clean(row.get("data-channel-id", ""))

    return {
        "name": name,
        "type": kind,
        "satellite_group": tp["satellite_group"],
        "spacecraft": tp["spacecraft"],
        "position": tp["position"],
        "frequency": tp["frequency"],
        "polarization": tp["polarization"],
        "symbol_rate": tp["symbol_rate"],
        "fec": tp["fec"],
        "system": tp["system"],
        "modulation": tp["modulation"],
        "sid": sid,
        "country": clean(cells[3].get_text(" ", strip=True)),
        "category": clean(cells[4].get_text(" ", strip=True)),
        "package": " / ".join(lines(cells[5])),
        "encryption": encryption,
        "free_to_air": free_to_air,
        "vpid": video_lines[0] if video_lines else "",
        "audio": " / ".join(audio_lines),
        "pmt_pid": clean(cells[10].get_text(" ", strip=True)),
        "pcr_pid": clean(cells[11].get_text(" ", strip=True)),
        "txt_pid": clean(cells[12].get_text(" ", strip=True)),
        "source_channel_id": int(data_channel_id) if data_channel_id.isdigit() else None,
        "updated": updated,
        "tp_id": tp["tp_id"],
    }


def parse_one(sat: dict[str, str]) -> dict[str, Any]:
    path = RAW / f"{sat['id']}.html"
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    dm = PAGE_DATE_RE.search(page_text)
    source_updated = dm.group(1) if dm else ""

    transponders: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for freq_table in soup.select("table.frequencies-table"):
        row = freq_table.find("tr", attrs={"data-frequency-id": True})
        if not row:
            continue
        tp = parse_frequency_row(row, sat)
        if not tp:
            continue
        details = freq_table.find_next_sibling("div")
        if details:
            channel_table = details.find("table", class_="fl")
            if channel_table:
                for channel_row in channel_table.find_all("tr", attrs={"data-channel-id": True}):
                    channel = parse_channel_row(channel_row, tp)
                    if not channel:
                        continue
                    key = (channel["frequency"], channel["polarization"], channel["sid"], channel["type"], channel["name"].casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    channels.append(channel)
                    tp["channel_count"] += 1
                    tp["radio_count" if channel["type"] == "RADIO" else "tv_count"] += 1
        if tp["channel_count"] > 0:
            transponders.append(tp)

    channels.sort(key=lambda x: (float(x["frequency"]), x["polarization"], x["sid"], x["name"].casefold()))
    transponders.sort(key=lambda x: (float(x["frequency"]), x["polarization"]))
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"name": "KingOfSat", "url": sat["url"], "last_updated": source_updated},
        "satellite": {"id": sat["id"], "name": sat["name"], "position": sat["position"]},
        "counts": {
            "transponders": len(transponders),
            "channels": len(channels),
            "tv": sum(c["type"] == "TV" for c in channels),
            "radio": sum(c["type"] == "RADIO" for c in channels),
        },
        "transponders": transponders,
        "channels": channels,
    }


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    satellites = json.loads(CONFIG.read_text(encoding="utf-8"))
    summary = {"generated_utc": datetime.now(timezone.utc).isoformat(), "source": "KingOfSat", "satellites": []}
    combined_channels: list[dict[str, Any]] = []
    combined_tps: list[dict[str, Any]] = []

    for sat in satellites:
        result = parse_one(sat)
        (OUTPUT / f"{sat['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["satellites"].append({"id": sat["id"], **result["counts"], "source_updated": result["source"]["last_updated"]})
        combined_channels.extend(result["channels"])
        combined_tps.extend(result["transponders"])

    combined = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": "KingOfSat",
        "satellites": summary["satellites"],
        "transponders": combined_tps,
        "channels": combined_channels,
    }
    (OUTPUT / "satellite_database.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "kingofsat_parse_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
