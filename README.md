# LolaBot

LolaBot - Telegram uchun o'zbekcha yordamchi bot. Bot `aiogram` bilan ishlaydi, AI javoblar uchun OpenRouter chat completions API’dan foydalanadi va Warzone/MW3 meta ma'lumotlarini AI’dan emas, meta parserlardan oladi.

## Imkoniyatlar

- Telegram bot `aiogram` 3 asosida ishlaydi.
- OpenRouter API orqali free text modeliga ulanadi.
- `OPENROUTER_API_KEY_1/2/3/4/5` bo'yicha key rotation ishlaydi.
- Oddiy chat `CHAT_MODEL` orqali ishlaydi.
- `CHAT_MODEL` limit yoki provider xatosiga tushsa `FALLBACK_MODEL` ishlaydi.
- Rasmda faqat `VISION_MODEL` ishlaydi.
- Matematika va murakkab reasoning savollar `REASONING_MODEL` orqali ishlaydi.
- `/image <prompt>` orqali OpenRouter image model bilan rasm yaratadi.
- `IMAGE_MODEL_1/2` bo'yicha image model fallback ishlaydi.
- Default chat model: `meta-llama/llama-3.3-70b-instruct:free`.
- Warzone/MW3 meta javoblari CODMunity parser + WZStatsGG fallback + chat state orqali beriladi.
- `MAIN_GROUP_ID` berilsa, asosiy guruh bot javob limitidan ozod bo'ladi.
- Telegram Stars orqali premium: 1 kun test 29 Stars, 1 oy premium 250 Stars.
- Guruhlarda xabar statistikasi: `/stats`, `/week`, `/month`.
- Har kuni 08:00 da guruhlarga kechagi daily report yuboradi.
- CODMunity yoki WZStatsGG'dan weapon name, type, pick rate, code va attachmentlar olinadi.
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
2. Bot avval CODMunity sahifasini parser qiladi, topolmasa WZStatsGG fallback ishlaydi.
3. Natija chat state ichida `last_meta_weapons` sifatida saqlanadi.
4. User `2 ni ber`, `ikkinchisini och`, `kogotni taxlab ber`, `mk.78` kabi yozsa, bot oxirgi ro'yxatdan qurolni tanlaydi.
5. Attachment kerak bo'lsa, tanlangan qurol sahifasi ochilib, loadout attachmentlari parser bilan olinadi.

Bot hech qachon eski yoki taxminiy meta aytmaydi. CODMunity va WZStatsGG kerakli data topolmasa:

```text
Meta manbalaridan aniq ma'lumot topilmadi, keyinroq qayta urinib ko'ring.
```

deb javob beradi.

## Statistika

Bot guruhlarda barcha xabarlarni sanaydi. Oddiy xabarlarga javob bermaydi; Lola bilan gaplashish uchun guruhda uning xabariga reply qilish yoki `@bot_username` bilan mention qilish kerak. Guruhda faqat exact `Lola` chaqiruvi random yumshoq javob qaytaradi; uzun gap ichida `Lola` tilga olinsa bot aralashmaydi. Guruhdagi photo, static sticker, GIF, animation, video, video sticker va video_note faqat private chatda, botga reply qilinganda yoki captionda `@bot_username` bo'lganda visionga yuboriladi. GIF/video/video sticker uchun 3-5 frame ajratiladi; animated `.tgs` sticker tushunilmasa bot fallback javob beradi va crash qilmaydi. Agar bot guruhdagi oddiy rasm update'larini umuman olmasa, BotFather orqali privacy mode'ni o'chiring: `/setprivacy` -> `Disable`. Statistika, memory va kunlik limitlar uchun PostgreSQL `DATABASE_URL` kerak. Private chat kuniga 10 ta, boshqa guruhlar kuniga 9 ta bepul bot javobidan foydalanadi. `MAIN_GROUP_ID` asosiy guruhni bepul qiladi.

Buyruqlar:

```text
/stats
/week
/month
/image quyosh botayotgan shahar
/premium
/chat_id
```

## Premium

Telegram Stars tariflari:

```text
1 kun test: 29 Stars
1 oy premium: 250 Stars
```

`/premium` private chatda tariflarni ko'rsatadi. To'lov `currency=XTR` orqali yuboriladi. `successful_payment` kelganda `users` va `payments` jadvallariga yoziladi.

Admin komandalar faqat `OWNER_ID` uchun private chatda ishlaydi:

```text
/paid
/income
/users
/check <user_id>
/grant <user_id> [days]
/revoke <user_id>
/keys_status
/vision_status
/chat_id
```

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
MAIN_GROUP_ID=
OWNER_ID=
OPENROUTER_API_KEY_1=
OPENROUTER_API_KEY_2=
OPENROUTER_API_KEY_3=
OPENROUTER_API_KEY_4=
OPENROUTER_API_KEY_5=
CHAT_MODEL=meta-llama/llama-3.3-70b-instruct:free
FALLBACK_MODEL=google/gemma-3-27b-it
VISION_MODEL=nex-agi/nex-n2-pro:free
REASONING_MODEL=google/gemini-3.5-flash
IMAGE_MODEL_1=sourceful/riverflow-v2.5-pro:free
IMAGE_MODEL_2=sourceful/riverflow-v2.5-fast:free
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
MAIN_GROUP_ID=
OWNER_ID=
OPENROUTER_API_KEY_1=
OPENROUTER_API_KEY_2=
OPENROUTER_API_KEY_3=
OPENROUTER_API_KEY_4=
OPENROUTER_API_KEY_5=
CHAT_MODEL=meta-llama/llama-3.3-70b-instruct:free
FALLBACK_MODEL=google/gemma-3-27b-it
VISION_MODEL=nex-agi/nex-n2-pro:free
REASONING_MODEL=google/gemini-3.5-flash
IMAGE_MODEL_1=sourceful/riverflow-v2.5-pro:free
IMAGE_MODEL_2=sourceful/riverflow-v2.5-fast:free
```

Railway `python bot.py` komandasi bilan botni worker sifatida ishga tushiradi.

## Eslatma

Bot polling rejimida ishlaydi. Telegram webhook kerak emas, shuning uchun Railway'da alohida web server ochish shart emas.
