import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "kingofsat_satellites.json").read_text(encoding="utf-8"))
REPORT = {"ok": True, "source": "KingOfSat", "satellites": []}

MINIMUMS = {
    "astra_19_2": {"channels": 500, "transponders": 50},
    "hotbird_13": {"channels": 500, "transponders": 50},
    "hellas_39": {"channels": 20, "transponders": 5},
}

for sat in CONFIG:
    path = ROOT / "output" / f"{sat['id']}.json"
    item = {"id": sat["id"], "ok": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = data["counts"]
        limits = MINIMUMS[sat["id"]]
        channels = data.get("channels", [])
        forbidden = [c for c in channels if c.get("type") not in {"TV", "RADIO"}]
        missing_core = [
            c for c in channels
            if not c.get("name") or not c.get("frequency") or not c.get("polarization") or not c.get("symbol_rate") or c.get("sid") is None
        ]
        item.update(counts)
        item["source_updated"] = data.get("source", {}).get("last_updated", "")
        item["forbidden_records"] = len(forbidden)
        item["missing_core_fields"] = len(missing_core)
        item["ok"] = (
            counts["channels"] >= limits["channels"]
            and counts["transponders"] >= limits["transponders"]
            and bool(item["source_updated"])
            and not forbidden
            and not missing_core
        )
        if not item["ok"]:
            item["error"] = "Kanal/TP sayısı, kaynak tarihi veya temel alan doğrulaması başarısız"
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}: {exc}"
    REPORT["satellites"].append(item)
    REPORT["ok"] = REPORT["ok"] and item["ok"]

(ROOT / "reports" / "kingofsat_validation_report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(REPORT, ensure_ascii=False, indent=2))
if not REPORT["ok"]:
    raise SystemExit("KingOfSat doğrulama başarısız; çıktı repoya yayımlanmayacak.")
