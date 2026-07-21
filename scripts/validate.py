import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "satellites.json").read_text(encoding="utf-8"))
REPORT = {"ok": True, "satellites": []}

MINIMUMS = {
    "astra_19_2": {"channels": 100, "transponders": 15},
    "hotbird_13": {"channels": 100, "transponders": 15},
    "hellas_39": {"channels": 20, "transponders": 5},
}

for sat in CONFIG:
    path = ROOT / "output" / f"{sat['id']}.json"
    item = {"id": sat["id"], "ok": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = data["counts"]
        limits = MINIMUMS[sat["id"]]
        item.update(counts)
        item["source_updated"] = data["source"].get("last_updated", "")
        item["ok"] = counts["channels"] >= limits["channels"] and counts["transponders"] >= limits["transponders"] and bool(item["source_updated"])
        if not item["ok"]:
            item["error"] = "Kanal/TP sayısı veya kaynak tarihi beklenen alt sınırın altında"
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}: {exc}"
    REPORT["satellites"].append(item)
    REPORT["ok"] = REPORT["ok"] and item["ok"]

(ROOT / "reports" / "validation_report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(REPORT, ensure_ascii=False, indent=2))
if not REPORT["ok"]:
    raise SystemExit("Doğrulama başarısız; çıktı repoya yayımlanmayacak.")
