<details>
<summary>Логотип</summary>

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

</details>

[![Sync](https://github.com/Nombah501/TInstaller-full-json/actions/workflows/sync.yml/badge.svg)](https://github.com/Nombah501/TInstaller-full-json/actions/workflows/sync.yml)
[![Pages](https://img.shields.io/badge/Pages-live-brightgreen)](https://nombah501.github.io/TInstaller-full-json/1.json)
[![JSON](https://img.shields.io/badge/format-TInstaller%20JSON-blue)](#использование-в-tinstaller)

Живой форк [topperbg.github.io/1.json](https://topperbg.github.io/1.json) — весь каталог на русском языке для **Amazon Fire TV Stick** и приложения **TInstaller**.

Ежедневно подтягивает оригинал (болгарский каталог topperbg, обновляется ежедневно) и точечно переводит только новые/изменённые описания. Остальное — из кэша.

> База динамическая: форк повторяет оригинал 1-в-1, только на русском — сколько приложений и категорий у topperbg, столько и здесь.

---

### Использование в TInstaller

1. Открой TInstaller и найди поле для URL JSON-каталога.
2. Введи одну из ссылок ниже — на пульте удобнее короткая.
3. Внимание: ссылка чувствительна к регистру: `69_C_` — заглавная `C` и нижнее подчёркивание (на пульте — на странице символов). Проще всего печатать с телефона: приложение Fire TV (Android/iOS) → клавиатура телефона печатает на ТВ.

**Короткая ссылка (для пульта)**

```
https://t.ly/69_C_
```

![QR для t.ly/69_C_](qr.png)

> Если короткая ссылка не сработала — t.ly это сторонний сервис и иногда недоступен (может отдать 403). Используй любой из двух вариантов ниже: они ведут на тот же файл.

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

## Для разработчика

### Что переводится

| Поле | Правило |
|------|---------|
| `description` | Полностью на русском, с эмодзи, списками и форматированием |
| `category` | Стабильный словарь: `Маркети`→`Маркеты` · `Инструменти`→`Инструменты` · `Ланчъри`→`Лаунчеры` · `Видеоплеъри`→`Видеоплееры` · `Браузъри`→`Браузеры` · `Скрийнсейвъри`→`Скринсейверы` · `Kodi repo`→`Kodi репозитории` · `Plex&Jellyfin`→`Plex и Jellyfin` · `Kodi Modi`→`Kodi Моды` и т.д. |
| `title` | Не трогается (бренды) |
| `url` / `mirror` / `ver` | Без изменений |

### Как работает автообновление

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
pip install deep-translator==1.11.4
python scripts/sync.py            # инкрементально
python scripts/sync.py --dry-run  # проверка без записи
python scripts/sync.py --force    # перевести всё заново (игнорируя кэш)
```

#### На GitHub

`.github/workflows/sync.yml` — `cron: 0 3 * * *` + `workflow_dispatch` (галочка `force`). Логи и бейдж — во вкладке **Actions**. Деплой Pages через `actions/deploy-pages`, публикация не зависит от `GITHUB_TOKEN`.

### Структура

```
1.json                        главный файл для TInstaller (RU)
ru.json                       алиас
data/translation_cache.json   кэш: bg hash → ru
data/upstream_snapshot.json   последний оригинал (для диффа)
scripts/translator.py         BG→RU, словарь категорий + глоссарий
scripts/sync.py               инкрементальный синк (ретраи, атомарная запись)
.github/workflows/sync.yml    daily sync
```

### О переводе

Первичный перевод выполнен LLM с вычиткой (исправлены `Поддържа`→`Поддерживает`, `Възможности`→`Возможности`, `Приложението`→`Приложение`, транслит `скрийнсейвър`→`скринсейвер`). Далее — инкрементально через API с чанкингом длинных описаний (>500 символов) и глоссарием.

---

### Лицензия

Данные — [topperbg](https://topperbg.github.io/). Форк — перевод и автоматизация.
