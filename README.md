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
