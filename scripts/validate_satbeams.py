import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "satbeams_satellites.json").read_text(encoding="utf-8"))
CANDIDATE_DIR = ROOT / "candidate" / "satbeams"
OUTPUT_DIR = ROOT / "output" / "satbeams"
REPORTS_DIR = ROOT / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

MAX_CHANNEL_DROP_RATIO = 0.30
MAX_TP_DROP_RATIO = 0.30
DEFAULT_MAX_UNKNOWN_QUALITY_RATIO = 0.15
UNKNOWN_QUALITY_WARNING_RATIO = 0.15
ALLOWED_TYPES = {"TV", "RADIO"}
ALLOWED_QUALITIES = {"SD", "HD", "4K", "UHD", "3D", "UNKNOWN", "RADIO"}


def digest(data):
    stable = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def identity(channel):
    source_id = channel.get("source_channel_id")
    if source_id is not None:
        return f"id:{source_id}"
    return f"{channel.get('tp_id')}:{channel.get('sid')}:{str(channel.get('name','')).casefold()}"


report = {
    "run_utc": datetime.now(timezone.utc).isoformat(),
    "ok": True,
    "should_publish": False,
    "source": "Satbeams API",
    "satellites": [],
}
validated = []

for sat in CONFIG:
    candidate_path = CANDIDATE_DIR / f"{sat['id']}.json"
    current_path = OUTPUT_DIR / f"{sat['id']}.json"
    item = {"id": sat["id"], "ok": False, "errors": [], "warnings": []}
    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        channels = candidate.get("channels") or []
        tps = candidate.get("transponders") or []
        counts = candidate.get("counts") or {}

        forbidden = [ch for ch in channels if ch.get("type") not in ALLOWED_TYPES]
        invalid_quality = [ch for ch in channels if ch.get("quality") not in ALLOWED_QUALITIES]
        missing_core = [ch for ch in channels if not ch.get("name") or ch.get("frequency") is None or not ch.get("polarization") or ch.get("symbol_rate") is None or ch.get("sid") is None]
        identities = [identity(ch) for ch in channels]
        duplicates = len(identities) - len(set(identities))
        unknown = sum(1 for ch in channels if ch.get("type") == "TV" and ch.get("quality") == "UNKNOWN")
        tv = max(1, sum(1 for ch in channels if ch.get("type") == "TV"))

        if len(channels) < sat["minimum_channels"]:
            item["errors"].append(f"Kanal sayısı düşük: {len(channels)} < {sat['minimum_channels']}")
        if len(tps) < sat["minimum_transponders"]:
            item["errors"].append(f"TP sayısı düşük: {len(tps)} < {sat['minimum_transponders']}")
        if forbidden:
            item["errors"].append(f"Yasaklı tür kaydı: {len(forbidden)}")
        if invalid_quality:
            item["errors"].append(f"Geçersiz kalite kaydı: {len(invalid_quality)}")
        if missing_core:
            item["errors"].append(f"Eksik temel alan: {len(missing_core)}")
        if duplicates:
            item["errors"].append(f"Tekrarlı kanal kimliği: {duplicates}")
        unknown_ratio = unknown / tv
        max_unknown_ratio = float(sat.get("max_unknown_quality_ratio", DEFAULT_MAX_UNKNOWN_QUALITY_RATIO))
        if unknown_ratio > max_unknown_ratio:
            item["errors"].append(
                f"Bilinmeyen kalite oranı yüksek: {unknown}/{tv} "
                f"({unknown_ratio:.1%} > {max_unknown_ratio:.1%})"
            )
        elif unknown_ratio > UNKNOWN_QUALITY_WARNING_RATIO:
            item["warnings"].append(
                f"Bilinmeyen kalite oranı dikkat gerektiriyor: {unknown}/{tv} ({unknown_ratio:.1%})"
            )

        old = None
        if current_path.exists():
            old = json.loads(current_path.read_text(encoding="utf-8"))
            old_channels = old.get("channels") or []
            old_tps = old.get("transponders") or []
            if old_channels and len(channels) < len(old_channels) * (1 - MAX_CHANNEL_DROP_RATIO):
                item["errors"].append(f"Anormal kanal düşüşü: {len(old_channels)} -> {len(channels)}")
            if old_tps and len(tps) < len(old_tps) * (1 - MAX_TP_DROP_RATIO):
                item["errors"].append(f"Anormal TP düşüşü: {len(old_tps)} -> {len(tps)}")

        item.update(counts)
        item["forbidden_records"] = len(forbidden)
        item["missing_core_fields"] = len(missing_core)
        item["duplicate_identities"] = duplicates
        item["candidate_hash"] = digest({"transponders": tps, "channels": channels})
        item["current_hash"] = digest({"transponders": old.get("transponders", []), "channels": old.get("channels", [])}) if old else ""
        item["changed"] = item["candidate_hash"] != item["current_hash"]

        if old:
            old_map = {identity(ch): ch for ch in old.get("channels", [])}
            new_map = {identity(ch): ch for ch in channels}
            item["added"] = len(new_map.keys() - old_map.keys())
            item["removed"] = len(old_map.keys() - new_map.keys())
            item["updated"] = sum(1 for key in new_map.keys() & old_map.keys() if new_map[key] != old_map[key])
        else:
            item["added"] = len(channels)
            item["removed"] = 0
            item["updated"] = 0

        item["ok"] = not item["errors"]
        if item["ok"]:
            validated.append((sat, candidate_path, current_path, item["changed"]))
    except Exception as exc:
        item["errors"].append(f"{type(exc).__name__}: {exc}")
    report["satellites"].append(item)
    report["ok"] = report["ok"] and item["ok"]

if report["ok"]:
    changed_any = False
    for sat, candidate_path, current_path, changed in validated:
        if current_path.exists() and changed:
            shutil.copy2(current_path, OUTPUT_DIR / f"{sat['id']}_previous.json")
        if changed or not current_path.exists():
            shutil.copy2(candidate_path, current_path)
            changed_any = True
    report["should_publish"] = changed_any

(REPORTS_DIR / "satbeams_validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
print(f"SHOULD_PUBLISH={'true' if report['should_publish'] else 'false'}")
if not report["ok"]:
    raise SystemExit("Satbeams doğrulama başarısız; mevcut sağlam çıktı korunuyor")
