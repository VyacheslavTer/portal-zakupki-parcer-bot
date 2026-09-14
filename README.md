# ICPortal Parser

Бот для мониторинга закупочных порталов по ключевым словам и отправки новых совпадений в Telegram.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
Copy-Item .env.example .env
```

## Запуск поиска

```powershell
.\.venv\Scripts\python.exe -m icportal_bot run
```

Бот ходит напрямую в API:

```text
https://icportal.kz/api/purchases
https://zakup.gov.kz/api/core/api/public/lots/
```

Браузер не открывается. Если API когда-нибудь начнет требовать авторизацию, можно будет добавить cookie/token, но сейчас публичный ответ уже содержит нужные данные.

## Настройки поиска

Ключевые слова и лимиты лежат в `config.json`:

```json
{
  "search": {
    "keywords": ["Photoshop", "Autodesk"],
    "max_results_per_keyword": 20,
    "max_pages_per_keyword": 5,
    "status": "open"
  }
}
```


`"status": "open"` оставляет только открытые закупки. Чтобы смотреть все статусы, поставьте `null`:

```json
"status": null
```

Дополнительные источники включаются отдельными блоками в `config.json`:

- `samruk` — публичный поиск Samruk-Kazyna, в боевом режиме оставляет закупки с отметкой "Осталось".
- `erg` — отдельный ERG-парсер через `erg_parser/config.json`.
- `govzakup` — публичный поиск `zakup.gov.kz`, оставляет опубликованные лоты с неистекшей датой приема заявок.

Если отдельный Samruk-парсер включен, для `govzakup` можно поставить:

```json
"excluded_system_ids": [3]
```

Так GovZakup не будет дублировать лоты площадки SKK/Samruk.

Для `max_keyword_checks` значение `0` означает "проверять весь словарь".

## Telegram

В `.env` укажите:

```env
TELEGRAM_BOT_TOKEN=123456:...
TELEGRAM_CHAT_ID=123456789
```

И включите отправку в `config.json`:

```json
"telegram_enabled": true
```

## Ежедневный запуск в Windows Task Scheduler

Программа: полный путь к `.\.venv\Scripts\python.exe`

Аргументы:

```text
-m icportal_bot run
```

Рабочая папка: путь к этому проекту.
