# راهنمای عامل‌های کدنویسی

این پوشه یک مخزن مستقل برای Flow Studio است. راهنمای شروع در [`init`](init) و طراحی فعلی در [`design.md`](design.md) است. پیش از تغییر رفتار، [`docs/decisions.md`](docs/decisions.md) و پیش از commit یا انتشار، [`docs/publication-security.md`](docs/publication-security.md) را بخوانید.

- موتور و رابط باید برای هر پروژهٔ Swagger/OpenAPI کار کنند. CLM فقط یک preset قابل‌ویرایش در `studio/presets.py` است.
- دادهٔ واقعی، schema واردشده، توکن، OTP، شمارهٔ هویتی، خروجی درخواست/پاسخ و فایل آپلودی را در Git یا مستندات قرار ندهید.
- تغییرات نیمه‌تمام دیگران را حفظ کنید. برای تقسیم کار و ادغام به [`docs/collaboration.md`](docs/collaboration.md) رجوع کنید.
- پس از تغییر کد، `python3 -m unittest discover -s tests -v` و `git diff --check` را اجرا کنید. تغییر رابط را با مرورگر و یک پایگاه دادهٔ آزمایشی جدا بررسی کنید.
