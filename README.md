# LolaBot

LolaBot - Telegram uchun o'zbekcha yordamchi bot. Bot `aiogram` bilan ishlaydi, AI javoblar uchun OpenRouter chat completions API’dan foydalanadi va Warzone/MW3 meta ma'lumotlarini AI’dan emas, CODMunity parseridan oladi.

## Imkoniyatlar

- Telegram bot `aiogram` 3 asosida ishlaydi.
- OpenRouter API orqali Gemma free modeliga ulanadi.
- Default model: `google/gemma-3-27b-it:free`.
- Warzone/MW3 meta javoblari CODMunity parser + chat state orqali beriladi.
- CODMunity'dan weapon name, type, pick rate, code va attachmentlar olinadi.
- Parser data topolmasa bot taxmin qilmaydi.
- Railway deploy uchun `Procfile` va `railway.toml` tayyor.
- API keylar kodga yozilmaydi, faqat `.env` yoki Railway variables orqali olinadi.

## Tuzilma

```text
.
+-- app/
|   +-- config.py
|   +-- main.py
|   +-- handlers/
|   |   +-- common.py
|   +-- services/
|       +-- ai_provider.py
|       +-- meta_engine.py
+-- bot.py
+-- requirements.txt
+-- Procfile
+-- railway.toml
+-- .env.example
```

## Meta logika

1. User `Warzone meta kerak` yoki `MW3 meta` deb yozadi.
2. Bot CODMunity sahifasini parser qiladi.
3. Natija chat state ichida `last_meta_weapons` sifatida saqlanadi.
4. User `2 ni ber`, `ikkinchisini och`, `kogotni taxlab ber`, `mk.78` kabi yozsa, bot oxirgi ro'yxatdan qurolni tanlaydi.
5. Attachment kerak bo'lsa, tanlangan qurol sahifasi ochilib, loadout attachmentlari parser bilan olinadi.

Bot hech qachon eski yoki taxminiy meta aytmaydi. CODMunity ishlamasa yoki parser kerakli data topolmasa:

```text
CODMunity'dan ma'lumot olishda muammo bo'ldi
```

deb javob beradi.

## Local ishga tushirish

```bash
python -m venv .venv
```

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

`.env.example` asosida `.env` yarating:

```env
TELEGRAM_BOT_TOKEN=
DATABASE_URL=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=google/gemma-3-27b-it:free
```

Botni ishga tushirish:

```bash
python bot.py
```

## Railway Deploy

Railway variables bo'limiga quyidagilarni kiriting:

```env
TELEGRAM_BOT_TOKEN=
DATABASE_URL=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=google/gemma-3-27b-it:free
```

Railway `python bot.py` komandasi bilan botni worker sifatida ishga tushiradi.

## Eslatma

Bot polling rejimida ishlaydi. Telegram webhook kerak emas, shuning uchun Railway'da alohida web server ochish shart emas.
