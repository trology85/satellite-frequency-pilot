# LyngSat Satellite Pilot

Bağımsız deneme hattı. Hedef sayfalar:

- Astra 1N/1P — 19.2°E
- Hotbird 13F/13G — 13.0°E
- Hellas Sat 3/4 — 39.0°E

## Akış

1. Playwright/Chromium sayfayı normal tarayıcı gibi açar.
2. Son DOM içeriği `raw/*.html` olarak kaydedilir.
3. Parser LyngSat tablolarındaki `rowspan` alanlarını çözer.
4. Her uydu için ayrı JSON ve birleşik `satellite_database.json` oluşturulur.
5. Kanal/TP sayıları anormalse workflow başarısız olur ve çıktı commit edilmez.
6. Ham HTML yalnız GitHub Actions artifact olarak 14 gün tutulur; repo şişmez.

## Yerel çalıştırma

```bash
pip install -r requirements.txt
python -m playwright install chromium
python scripts/fetch_pages.py
python scripts/parse_lyngsat.py
python scripts/validate.py
```

## Not

Bu pilot çıktılarını doğrudan uygulama veritabanına bağlamaz. Önce birkaç çalışma boyunca doğruluk kontrolü yapılmalıdır. Kaynak kullanım ve yeniden yayın koşulları ayrıca değerlendirilmelidir.

## Satbeams kalite tamamlama

Satbeams API ana kaynaktır. TV kaydının `resolution` alanı boş olduğunda workflow aynı uyduyu KingOfSat'tan indirir ve yalnız güvenli eşleşmede kaliteyi tamamlar.

Eşleşme anahtarı: uydu dosyası + polarizasyon + SID + frekans toleransı (1 MHz) + sembol oranı toleransı (2). Kanal adı ayrıca doğrulanır. Birden fazla/çelişkili aday varsa kayıt değiştirilmez ve `UNKNOWN` kalır.

Ayrıntılı eşleştirme kayıtları yalnız `reports/satbeams_quality_enrichment_report.json` artifact'ında tutulur. Uygulamanın kullandığı `output/satbeams/*.json` dosyalarına log, güven puanı veya eşleştirme kaynağı alanı eklenmez.
