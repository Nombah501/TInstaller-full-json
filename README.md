```
┌─────────────────────────────────────────────────────┐
│                                                     │
│   ████████╗ ██╗███╗   ██╗███████╗████████╗ █████╗   │
│   ╚══██╔══╝ ██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗  │
│      ██║    ██║██╔██╗ ██║███████╗   ██║   ███████║  │
│      ██║    ██║██║╚██╗██║╚════██║   ██║   ██╔══██║  │
│      ██║    ██║██║ ╚████║███████║   ██║   ██║  ██║  │
│      ╚═╝    ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝  │
│                                                     │
│          русскоязычный форк  ·  Fire TV Stick       │
│            topperbg  ──BG──►  RU  ·  daily          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

[![Sync](https://github.com/Nombah501/TInstaller-full-json/actions/workflows/sync.yml/badge.svg)](https://github.com/Nombah501/TInstaller-full-json/actions/workflows/sync.yml)
[![Pages](https://img.shields.io/badge/Pages-live-brightgreen)](https://nombah501.github.io/TInstaller-full-json/1.json)
[![JSON](https://img.shields.io/badge/format-TInstaller%20JSON-blue)](#использование)

Живой форк [topperbg.github.io/1.json](https://topperbg.github.io/1.json) — весь каталог на русском языке для **Amazon Fire TV Stick** и приложения **TInstaller**.

Ежедневно подтягивает оригинал (болгарский → обновляется каждый день) и точечно переводит только новые/изменённые описания. Остальное — из кэша.

> База динамическая: сегодня ~200 приложений в 14 категориях, завтра может быть больше/меньше — форк повторяет оригинал 1-в-1, только на русском.

---

### 📺 Использование в TInstaller

Вставь в поле URL JSON один из вариантов (на пульте Fire TV удобнее короткий):

**Короткая ссылка (рекомендуется для пульта)**
```
https://t.ly/69_C_
```

**GitHub Pages**
```
https://nombah501.github.io/TInstaller-full-json/1.json
```

**Raw (работает и без Pages)**
```
https://raw.githubusercontent.com/Nombah501/TInstaller-full-json/main/1.json
```

Также доступен алиас `ru.json` по тем же путям. Формат совместим: `{"apps": [{title, description, category, url, mirror, ver, ...}]}`.

---

### 🔤 Что переводится

| Поле | Правило |
|------|---------|
| `description` | Полностью на русский, с эмодзи, списками и форматированием |
| `category` | Стабильный словарь: `Маркети`→`Маркеты` · `Инструменти`→`Инструменты` · `Ланчъри`→`Лаунчеры` · `Видеоплеъри`→`Видеоплееры` · `Браузъри`→`Браузеры` · `Скрийнсейвъри`→`Скринсейверы` · `Kodi repo`→`Kodi репозитории` · `Plex&Jellyfin`→`Plex и Jellyfin` · `Kodi Modi`→`Kodi Моды` и т.д. |
| `title` | Не трогается (бренды) |
| `url` / `mirror` / `ver` | Без изменений |

---

### ⚙️ Как работает автообновление

```
                         ┌──────────────────────┐
  https://topperbg.github.io/1.json ──►│   scripts/sync.py  │──► 1.json (RU)
                         │         │              │     ru.json
                         │    sha256(bg_text)    │
                         │         │              │
                         │         ▼              │
                         │ data/translation_     │
                         │      cache.json ◄─────┘
                         │         ▲
                         │ data/upstream_        │
                         │  snapshot.json        │
                         └──────────────────────┘
```

- `sync.py` считает `sha256` каждого болгарского `description`/`category`
- **hit** → берёт готовый перевод из `data/translation_cache.json` (мгновенно)
- **miss** → переводит через `MyMemory` (бесплатно, без ключа) с ретраями + фолбэк `LibreTranslate`, сохраняет в кэш
- Коммитит только если upstream действительно изменился — ручные правки в кэше сохраняются

#### Локально

```bash
pip install deep-translator
python scripts/sync.py            # инкрементально
python scripts/sync.py --dry-run  # проверка без записи
python scripts/sync.py --force    # переперевести всё
```

#### На GitHub

`.github/workflows/sync.yml` — `cron: 0 3 * * *` + `workflow_dispatch` (галочка `force`). Логи и бейдж — во вкладке **Actions**.

---

### 📂 Структура

```
1.json                        главный файл для TInstaller (RU)
ru.json                       алиас
data/translation_cache.json   кэш: bg hash → ru
data/upstream_snapshot.json   последний оригинал (для диффа)
scripts/translator.py         BG→RU, словарь категорий
scripts/sync.py               инкрементальный синк
.github/workflows/sync.yml    daily sync
```

---

### 📝 О переводе

Первичный перевод выполнен LLM с вычиткой (исправлены `Поддържа`→`Поддерживает`, `Възможности`→`Возможности`, `Приложението`→`Приложение`, транслит `скрийнсейвър`→`скринсейвер`). Далее — инкрементально через API.

---

### Лицензия

Данные — [topperbg](https://topperbg.github.io/). Форк — перевод и автоматизация.
