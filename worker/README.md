# Lola automatic video worker

Bu worker Lola serveridan alohida, Jasurning PC'sida ishlaydi. U Telegram update polling qilmaydi. PostgreSQL queue'dan vazifa oladi, videoni PC'da yuklaydi va FFmpeg bilan Telegram uchun MP4 qiladi.

## Natija

1. Guruhdagi odam YouTube, Instagram, TikTok yoki X link yuboradi.
2. Lola serveri linkni AI'ga yubormasdan PostgreSQL queue'ga yozadi.
3. PC worker videoni yuklaydi.
4. Video Lola nomidan caption va reply'siz yuboriladi.
5. Video muvaffaqiyatli yuborilgandan keyingina original link o'chiriladi.
6. Xato bo'lsa link o'chmaydi va guruhga xato yozuvi yuborilmaydi.

## Windows o'rnatish

Repository papkasida PowerShell yoki CMD oching:

```bat
py -m venv .venv-worker
.venv-worker\Scripts\python.exe -m pip install -r worker\requirements.txt
copy .env.worker.example .env.worker
```

`.env.worker` ichida quyidagilarni to'ldiring:

```env
TELEGRAM_BOT_TOKEN=Lola_bot_tokeni
DATABASE_URL=Railway_PostgreSQL_tashqi_URL
VIDEO_WORKER_ID=jasur-pc
```

Worker'ni ishga tushirish:

```bat
.venv-worker\Scripts\python.exe -m worker.video_worker
```

## Railway variables

PC worker tayyor va ishlayotganidan keyin Lola Railway service'ga qo'shing:

```env
VIDEO_LINKS_ENABLED=true
VIDEO_LINKS_CHAT_IDS=-1001234567890
```

`VIDEO_LINKS_CHAT_IDS` majburiy allow-list. Bo'sh bo'lsa funksiya yoqilmaydi. Bir nechta ruxsat berilgan guruh ID'sini vergul bilan yozish mumkin.

## Telegram ruxsatlari

- Lola guruhda admin bo'lishi va xabarlarni o'chirish huquqiga ega bo'lishi kerak.
- BotFather'da Group Privacy Mode o'chirilgan bo'lishi kerak, aks holda oddiy link xabarlari Lolaga kelmaydi.

## Xavfsiz ishga tushirish tartibi

1. Avval branchdagi server kodini deploy qiling, lekin `VIDEO_LINKS_ENABLED=false` qolsin.
2. PC worker'ni ishga tushiring va logda `Lola video worker started` chiqishini tekshiring.
3. Faqat test guruh ID'sini `VIDEO_LINKS_CHAT_IDS`ga kiriting.
4. `VIDEO_LINKS_ENABLED=true` qiling.
5. Bitta qisqa link bilan sinang.
6. Link o'chib, faqat captionsiz video qolganini tekshiring.
7. Shundan keyin asosiy guruh ID'siga o'ting.
