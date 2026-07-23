import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "satbeams_satellites.json").read_text(encoding="utf-8"))
CANDIDATE_DIR = ROOT / "candidate" / "satbeams"
KING_DIR = ROOT / "output"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

KNOWN = {"SD", "HD", "UHD", "4K", "3D"}
FREQUENCY_TOLERANCE_MHZ = 1.0
SYMBOL_RATE_TOLERANCE = 2
NAME_SIMILARITY_MIN = 0.82


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\b(?:hd|uhd|4k|sd|tv|television|channel)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def recalc_counts(document: dict[str, Any]) -> None:
    channels = document.get("channels") or []
    type_counts = Counter(ch.get("type") for ch in channels)
    quality_counts = Counter(ch.get("quality") for ch in channels if ch.get("type") == "TV")
    counts = document.setdefault("counts", {})
    counts.update({
        "channels": len(channels),
        "tv": type_counts.get("TV", 0),
        "radio": type_counts.get("RADIO", 0),
        "sd": quality_counts.get("SD", 0),
        "hd": quality_counts.get("HD", 0),
        "uhd_4k": quality_counts.get("UHD", 0) + quality_counts.get("4K", 0),
        "unknown_quality": quality_counts.get("UNKNOWN", 0),
    })


def quality_of(channel: dict[str, Any]) -> str:
    q = clean(channel.get("quality")).upper()
    if q == "4K":
        return "UHD"
    return q if q in KNOWN else ""


def candidate_matches(target: dict[str, Any], king_channels: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float, str]]:
    tf = number(target.get("frequency"))
    tsr = integer(target.get("symbol_rate"))
    tsid = integer(target.get("sid"))
    tpol = clean(target.get("polarization")).upper()
    tname = norm_name(target.get("name"))
    if tf is None or tsid is None or not tpol:
        return []

    matches = []
    for source in king_channels:
        q = quality_of(source)
        if not q:
            continue
        sf = number(source.get("frequency"))
        ssr = integer(source.get("symbol_rate"))
        ssid = integer(source.get("sid"))
        spol = clean(source.get("polarization")).upper()
        if sf is None or ssid is None:
            continue
        if spol != tpol or ssid != tsid:
            continue
        if abs(sf - tf) > FREQUENCY_TOLERANCE_MHZ:
            continue
        if tsr is not None and ssr is not None and abs(ssr - tsr) > SYMBOL_RATE_TOLERANCE:
            continue

        sname = norm_name(source.get("name"))
        similarity = SequenceMatcher(None, tname, sname).ratio() if tname and sname else 0.0
        exact_name = bool(tname and sname and tname == sname)
        confidence = "exact_tp_sid_name" if exact_name else "exact_tp_sid"
        matches.append((source, similarity, confidence))
    return matches


def main() -> None:
    report = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Satbeams + KingOfSat quality enrichment",
        "ok": True,
        "satellites": [],
    }

    for sat in CONFIG:
        item = {
            "id": sat["id"],
            "unknown_before": 0,
            "filled": 0,
            "filled_sd": 0,
            "filled_hd": 0,
            "filled_uhd": 0,
            "filled_3d": 0,
            "ambiguous": 0,
            "name_mismatch": 0,
            "not_found": 0,
            "unknown_after": 0,
            "matches": [],
        }
        candidate_path = CANDIDATE_DIR / f"{sat['id']}.json"
        king_path = KING_DIR / f"{sat['id']}.json"
        if not candidate_path.exists() or not king_path.exists():
            item["ok"] = False
            item["error"] = "Aday veya KingOfSat JSON bulunamadı"
            report["ok"] = False
            report["satellites"].append(item)
            continue

        document = json.loads(candidate_path.read_text(encoding="utf-8"))
        king = json.loads(king_path.read_text(encoding="utf-8"))
        king_channels = king.get("channels") or []

        for channel in document.get("channels") or []:
            if channel.get("type") != "TV" or clean(channel.get("quality")).upper() != "UNKNOWN":
                continue
            item["unknown_before"] += 1
            matches = candidate_matches(channel, king_channels)
            if not matches:
                item["not_found"] += 1
                continue

            qualities = {quality_of(source) for source, _, _ in matches}
            if len(matches) > 1 and len(qualities) > 1:
                item["ambiguous"] += 1
                continue

            matches.sort(key=lambda value: value[1], reverse=True)
            source, similarity, confidence = matches[0]
            if len(matches) > 1 and matches[1][1] == similarity and norm_name(matches[1][0].get("name")) != norm_name(source.get("name")):
                item["ambiguous"] += 1
                continue

            if confidence != "exact_tp_sid_name" and similarity < NAME_SIMILARITY_MIN:
                item["name_mismatch"] += 1
                continue

            quality = quality_of(source)
            if quality not in KNOWN:
                item["not_found"] += 1
                continue

            channel["quality"] = quality
            item["filled"] += 1
            item[f"filled_{quality.lower()}"] += 1
            item["matches"].append({
                "satbeams_id": channel.get("source_channel_id"),
                "kingofsat_id": source.get("source_channel_id"),
                "frequency": channel.get("frequency"),
                "polarization": channel.get("polarization"),
                "symbol_rate": channel.get("symbol_rate"),
                "sid": channel.get("sid"),
                "satbeams_name": channel.get("name"),
                "kingofsat_name": source.get("name"),
                "quality": quality,
                "confidence": confidence,
                "name_similarity": round(similarity, 4),
            })

        recalc_counts(document)
        item["unknown_after"] = document.get("counts", {}).get("unknown_quality", 0)
        item["ok"] = True
        candidate_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        report["satellites"].append(item)

    (REPORTS_DIR / "satbeams_quality_enrichment_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "ok": report["ok"],
        "satellites": [
            {k: v for k, v in item.items() if k not in {"matches"}}
            for item in report["satellites"]
        ],
    }, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit("Kalite zenginleştirme başarısız")


if __name__ == "__main__":
    main()
