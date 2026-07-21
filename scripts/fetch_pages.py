import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "satellites.json"
RAW = ROOT / "raw"
REPORTS = ROOT / "reports"

async def main() -> None:
    RAW.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    satellites = json.loads(CONFIG.read_text(encoding="utf-8"))
    report = {"run_utc": datetime.now(timezone.utc).isoformat(), "pages": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1365, "height": 900},
        )
        page = await context.new_page()

        for sat in satellites:
            item = {"id": sat["id"], "url": sat["url"], "ok": False}
            try:
                response = await page.goto(sat["url"], wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(3500)
                html = await page.content()
                status = response.status if response else None
                title = await page.title()
                item.update({"status": status, "title": title, "bytes": len(html.encode("utf-8"))})

                if status != 200:
                    raise RuntimeError(f"HTTP {status}")
                if "Frequency" not in html or "Channel Name" not in html or len(html) < 50_000:
                    raise RuntimeError("Beklenen LyngSat frekans tablosu bulunamadı")

                path = RAW / f"{sat['id']}.html"
                path.write_text(html, encoding="utf-8")
                item["ok"] = True
                item["file"] = str(path.relative_to(ROOT))
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            report["pages"].append(item)

        await browser.close()

    (REPORTS / "fetch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failed = [p for p in report["pages"] if not p["ok"]]
    if failed:
        raise SystemExit(f"{len(failed)} sayfa indirilemedi. reports/fetch_report.json dosyasına bakın.")

if __name__ == "__main__":
    asyncio.run(main())
