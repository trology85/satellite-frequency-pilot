import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "satbeams_satellites.json").read_text(encoding="utf-8"))
RAW_DIR = ROOT / "raw" / "satbeams"
CANDIDATE_DIR = ROOT / "candidate" / "satbeams"
REPORTS_DIR = ROOT / "reports"
CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = {"TV", "RADIO"}
ALLOWED_QUALITIES = {"SD", "HD", "4K", "UHD", "3D", "UNKNOWN"}


def clean(value):
    return " ".join(str(value or "").split())


def normalize_type(value):
    text = clean(value).upper()
    if text == "TV":
        return "TV"
    if text in {"RADIO", "RADYO"}:
        return "RADIO"
    return ""


def normalize_quality(value, channel_type):
    if channel_type == "RADIO":
        return "RADIO"
    text = clean(value).upper().replace("ULTRA HD", "UHD")
    aliases = {"2160P": "UHD", "4K UHD": "UHD", "FULL HD": "HD", "1080P": "HD", "720P": "HD"}
    text = aliases.get(text, text)
    return text if text in ALLOWED_QUALITIES else "UNKNOWN"


def audio_text(audio_pids):
    parts = []
    for audio in audio_pids or []:
        pid = audio.get("pid")
        lang = clean(audio.get("iso") or audio.get("language"))
        if pid is None:
            continue
        parts.append(f"{pid} / {lang}" if lang else str(pid))
    return " / ".join(parts)


def encryption_text(values):
    names = []
    for value in values or []:
        if isinstance(value, dict):
            name = clean(value.get("name") or value.get("label") or value.get("title"))
        else:
            name = clean(value)
        if name and name not in names:
            names.append(name)
    return " / ".join(names)


def package_text(values):
    names = []
    for value in values or []:
        if isinstance(value, dict):
            name = clean(value.get("name") or value.get("label") or value.get("title"))
        else:
            name = clean(value)
        if name and name not in names:
            names.append(name)
    return " / ".join(names)


report = {"ok": True, "source": "Satbeams API", "satellites": []}
for sat in CONFIG:
    raw = json.loads((RAW_DIR / f"{sat['id']}.json").read_text(encoding="utf-8"))
    source_tps = raw.get("data", {}).get("transponders", [])
    channels = []
    transponders = []
    seen_channels = set()

    for tp in source_tps:
        frequency = tp.get("frequency")
        polarization = clean(tp.get("polarisation")).upper()
        symbol_rate = tp.get("symbol_rate")
        tp_id = f"{sat['id']}:{frequency}:{polarization}:{symbol_rate}"
        kept = []

        for channel in tp.get("channels") or []:
            channel_type = normalize_type(channel.get("type"))
            if channel_type not in ALLOWED_TYPES:
                continue
            name = clean(channel.get("name"))
            sid = channel.get("sid")
            source_id = channel.get("id")
            identity = str(source_id) if source_id is not None else f"{tp_id}:{sid}:{name.casefold()}"
            if identity in seen_channels:
                continue
            if not name or frequency is None or not polarization or symbol_rate is None or sid is None:
                continue
            seen_channels.add(identity)
            quality = normalize_quality(channel.get("resolution"), channel_type)
            encryption = encryption_text(channel.get("encryptions"))
            record = {
                "name": name,
                "type": channel_type,
                "quality": quality,
                "satellite_group": sat["name"],
                "spacecraft": clean(tp.get("satellite_name")),
                "position": sat["position_label"],
                "frequency": frequency,
                "polarization": polarization,
                "symbol_rate": symbol_rate,
                "fec": clean(tp.get("fec")),
                "system": clean(tp.get("encoding")),
                "modulation": clean(tp.get("modulation")),
                "sid": sid,
                "country": clean(channel.get("country")),
                "country_code": clean(channel.get("country_code")),
                "beam": clean(tp.get("beam_name")),
                "provider": clean(tp.get("provider")),
                "package": package_text(channel.get("packages")),
                "encryption": encryption,
                "free_to_air": not bool(encryption),
                "compression": clean(channel.get("compression")),
                "vpid": channel.get("vpid"),
                "audio": audio_text(channel.get("audio_pids")),
                "nid": tp.get("nid"),
                "tid": tp.get("tid"),
                "source_channel_id": source_id,
                "source_transponder_id": tp.get("id"),
                "updated": clean(channel.get("date")),
                "tp_id": tp_id,
            }
            channels.append(record)
            kept.append(record)

        if kept:
            type_counts = Counter(ch["type"] for ch in kept)
            transponders.append({
                "tp_id": tp_id,
                "satellite_group": sat["name"],
                "spacecraft": clean(tp.get("satellite_name")),
                "position": sat["position_label"],
                "frequency": frequency,
                "polarization": polarization,
                "transponder": str(tp.get("id") or ""),
                "beam": clean(tp.get("beam_name")),
                "system": clean(tp.get("encoding")),
                "modulation": clean(tp.get("modulation")),
                "symbol_rate": symbol_rate,
                "fec": clean(tp.get("fec")),
                "network": clean(tp.get("provider")),
                "nid": tp.get("nid"),
                "tid": tp.get("tid"),
                "channel_count": len(kept),
                "tv_count": type_counts.get("TV", 0),
                "radio_count": type_counts.get("RADIO", 0),
                "source_transponder_id": tp.get("id"),
            })

    channels.sort(key=lambda c: (float(c["frequency"]), c["polarization"], int(c["sid"]), c["name"].casefold()))
    transponders.sort(key=lambda tp: (float(tp["frequency"]), tp["polarization"], int(tp["symbol_rate"] or 0)))
    type_counts = Counter(ch["type"] for ch in channels)
    quality_counts = Counter(ch["quality"] for ch in channels if ch["type"] == "TV")
    dates = sorted((ch["updated"] for ch in channels if ch["updated"]), reverse=True)

    output = {
        "schema_version": 2,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "Satbeams API",
            "url": f"https://www.satbeams.com/channels?position={sat['position']}E",
            "last_updated": dates[0] if dates else datetime.now(timezone.utc).date().isoformat(),
        },
        "satellite": {
            "id": sat["id"],
            "name": sat["name"],
            "position": sat["position_label"],
        },
        "counts": {
            "transponders": len(transponders),
            "channels": len(channels),
            "tv": type_counts.get("TV", 0),
            "radio": type_counts.get("RADIO", 0),
            "sd": quality_counts.get("SD", 0),
            "hd": quality_counts.get("HD", 0),
            "uhd_4k": quality_counts.get("UHD", 0) + quality_counts.get("4K", 0),
            "unknown_quality": quality_counts.get("UNKNOWN", 0),
        },
        "transponders": transponders,
        "channels": channels,
    }
    out_path = CANDIDATE_DIR / f"{sat['id']}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    item = {"id": sat["id"], "ok": bool(channels and transponders), **output["counts"], "candidate": str(out_path.relative_to(ROOT))}
    report["satellites"].append(item)
    report["ok"] = report["ok"] and item["ok"]

(REPORTS_DIR / "satbeams_parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if not report["ok"]:
    raise SystemExit("Satbeams parse başarısız")
