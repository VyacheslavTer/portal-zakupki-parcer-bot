# ERG Parser Probe

Отдельная песочница для проверки `https://torgi.erg.kz/supplier/#/competitions`.

Рабочий ICPortal-бот в `icportal_bot/` не импортирует этот код.

## Диагностика

```powershell
C:\Users\v.terechshenko\AppData\Local\Python\bin\python.exe .\erg_parser\diagnose_erg.py --timeout 20 --limit 3
```

Скрипт проверяет публичный API:

```text
https://torgi.erg.kz/api/SupplierAuctionService/GetAuctions
```

Цель текущего этапа: понять, какие запросы отвечают без авторизации, сколько занимают по времени, какие поля реально приходят, и где нужен логин/cookie.

## Отдельный запуск ERG

Создайте рабочий конфиг:

```powershell
Copy-Item .\erg_parser\config.example.json .\erg_parser\config.json
```

Проверка без записи в базу отправленных:

```powershell
C:\Users\v.terechshenko\AppData\Local\Python\bin\python.exe .\erg_parser\parser.py --dry-run --show-all
```

Обычный запуск:

```powershell
C:\Users\v.terechshenko\AppData\Local\Python\bin\python.exe .\erg_parser\parser.py
```

Или:

```powershell
.\run_erg_parser.bat
```

Проверка одного слова:

```powershell
C:\Users\v.terechshenko\AppData\Local\Python\bin\python.exe .\erg_parser\parser.py --keyword программ --dry-run --show-all
```

Проверка части списка:

```powershell
C:\Users\v.terechshenko\AppData\Local\Python\bin\python.exe .\erg_parser\parser.py --start-at 0 --max-keywords 10 --dry-run --show-all
```

В режиме по умолчанию `search_mode = "server_keywords"` парсер отправляет в ERG такие же запросы, как поле "Наименование позиции в спецификации". Это медленно, зато находит совпадения внутри позиций, например `программ` в конкурсе `T/37196/31/08/26`.

Запасной режим `search_mode = "active_local"` берет активные конкурсы по `AuStatus=4` и ищет ключевые слова локально по строкам списка. Он быстрее, но может пропустить совпадение, если слово есть только внутри позиций карточки.
