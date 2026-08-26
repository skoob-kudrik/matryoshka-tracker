# Матрёшка-трекер — доходность фонда vs индекс

Сервис собирает дневные данные доходности ОПИФ **«Матрёшка а-ля Рус»**
(Альфа-Капитал) и индекса **MCFTR** (Индекс МосБиржи полной доходности), хранит
их в SQLite и строит автономный HTML-график сравнения динамики с выбором
интервалов.

## Состав

| Файл | Назначение |
|------|------------|
| `collect.py` | Сбор данных → SQLite (`matryoshka.db`). Запускать ежедневно. |
| `build_chart.py` | Генерация `chart.html` из базы. |
| `matryoshka.db` | База (создаётся автоматически). |
| `chart.html` | Готовый график — открывается в браузере, интернет не нужен. |

## Источники

- **Фонд** — страница [alfacapital.ru/.../opif-matryoshka/cost](https://www.alfacapital.ru/disclosure/pifs/opif-matryoshka/cost).
  Данные встроены в HTML (`window.__SERVER_STATE__.navData`): стоимость пая и СЧА.
  Отдаётся окно последних ~60 дней. Публичного API на полную историю нет, поэтому
  для разового бэкфила используется выгрузка с investfunds.ru (см. ниже).
- **Индекс** — открытый ISS API Мосбиржи `iss.moex.com` (без ключей),
  тикер `MCFTR`, дневные значения закрытия.

Токены/ключи не нужны — оба источника публичные.

## Быстрый старт

```bash
cd matryoshka-tracker

# 1. Первый сбор: 60 дней фонда со страницы + полная история индекса
python3 collect.py --full

# 2. Сгенерировать график
python3 build_chart.py

# 3. Открыть chart.html в браузере
open chart.html
```

## Ежедневный запуск

Инкрементальный режим (без `--full`): фонд обновляется из 60-дневного окна
(перекрывает любые пропуски), индекс догружается от последней даты с запасом
10 дней. Апсерт по дате исключает дубли.

```bash
python3 collect.py && python3 build_chart.py
```

**Устойчивость к сбоям сети.** При сетевой ошибке (отвал DNS/интернета) каждый
запрос повторяется — по умолчанию **3 попытки с паузой 5 минут**. Настраивается:

```bash
python3 collect.py --retries 3 --retry-delay 300
```

Если все попытки исчерпаны — запуск завершится ошибкой, но данные не потеряются:
на следующем успешном сборе пропуск доберётся (окно фонда 60 дней + до-качка
индекса за 10 дней).

### launchd (macOS) — запуск каждый будний день в 16:00

Создай `~/Library/LaunchAgents/ru.matryoshka.collect.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ru.matryoshka.collect</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>cd /Users/kudrik/claude-workspace/matryoshka-tracker &amp;&amp; /usr/bin/python3 collect.py &amp;&amp; /usr/bin/python3 build_chart.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>/tmp/matryoshka.log</string>
  <key>StandardErrorPath</key><string>/tmp/matryoshka.err</string>
</dict>
</plist>
```

Загрузить:

```bash
launchctl load ~/Library/LaunchAgents/ru.matryoshka.collect.plist
```

### cron (альтернатива)

```
0 16 * * 1-5 cd /Users/kudrik/claude-workspace/matryoshka-tracker && /usr/bin/python3 collect.py && /usr/bin/python3 build_chart.py >> /tmp/matryoshka.log 2>&1
```

## Публикация в web (GitHub Actions + Pages)

Весь пайплайн можно унести в облако — тогда локальный `launchd` не нужен, а
график лежит по публичной ссылке и обновляется сам. Всё бесплатно (для
публичного репозитория минуты Actions не тарифицируются).

Как устроено (`.github/workflows/update.yml`):

- по будням в **16:00 МСК** (cron в UTC — `0 13 * * 1-5`) + кнопка ручного
  запуска (`workflow_dispatch`);
- job `build`: `collect.py` → `build_chart.py`, коммит свежих `matryoshka.db` и
  `chart.html` обратно в репозиторий (история копится в git), затем выгрузка
  `chart.html` как артефакта Pages (`_site/index.html`);
- job `deploy`: публикация на GitHub Pages.

**База — источник истории.** `collect.py` тянет со страницы фонда лишь окно
~60 дней; полная история (307+ дней) живёт в `matryoshka.db`, поэтому база
коммитится в репозиторий и участвует в каждом запуске.

### Первичная настройка (делается один раз)

```bash
cd matryoshka-tracker
git init
git add .
git commit -m "matryoshka-tracker: сборщик + график"

# создать пустой репозиторий на github.com, затем:
git remote add origin https://github.com/<логин>/matryoshka-tracker.git
git branch -M main
git push -u origin main
```

Дальше в настройках репозитория на GitHub:

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Actions → «Обновление графика» → Run workflow** — прогнать вручную и
   убедиться, что сбор проходит (важно проверить, что `alfacapital.ru` и
   `iss.moex.com` доступны с раннеров GitHub — они в США; MOEX ISS открыт
   глобально, сайт Альфа обычно тоже доступен).

После успешного запуска график будет по адресу
`https://<логин>.github.io/matryoshka-tracker/`.

> Нюансы GitHub cron: запуск может задержаться на 5–15 минут в пик — не
> критично, т.к. фонд публикует данные с лагом T+1, а окна сбора перекрываются
> и сами добирают пропуски. Расписание засыпает, если в репозитории 60 дней нет
> активности, но ежедневный коммит базы держит его «живым».

### Отключить локальный launchd

Когда пайплайн переехал в облако, локальный агент можно выгрузить, чтобы данные
не собирались в двух местах:

```bash
launchctl unload ~/Library/LaunchAgents/ru.matryoshka.collect.plist
```

### Альтернативы

- **VPS + cron** — свои `collect.py`/`build_chart.py` по расписанию, `chart.html`
  раздаётся nginx. Больше контроля (свой регион/IP), но нужен сервер и деньги.
- **Yandex Cloud Function по таймеру** — для размещения во внутреннем/российском
  периметре; график можно класть в Object Storage с публичным доступом.

## Разовый бэкфил полной истории фонда

Страница Альфа-Капитала отдаёт только ~60 дней. Полную историю пая берём из
выгрузки investfunds.ru:

1. Выгрузи Excel со страницы [investfunds.ru/funds/12035](https://investfunds.ru/funds/12035/)
   (колонки **Дата / Пай / СЧА**).
2. Положи файл в эту папку.
3. Импортируй:

   ```bash
   python3 collect.py --import-fund matryoshka-a-la-rus.xlsx --skip-fund --skip-index
   ```

Поддерживаются `.xlsx` и `.csv` (парсинг без внешних зависимостей; даты — как
Excel-серийники, так и `ДД.ММ.ГГГГ`/ISO). Апсерт по дате: повторный импорт и
ежедневный сбор со страницы совместимы, дубли не появятся.

> Уже выполнено: импортировано 307 дней (21.04.2025 … 21.07.2026). Фонд и индекс
> покрывают один период — сравнение честное на всех интервалах.

## График

`chart.html` — самодостаточный файл (данные встроены при генерации):

- переключатель режима **Доходность / СЧА**:
  - **Доходность** — сравнение фонда и индекса MCFTR в % (ниже);
  - **СЧА** — динамика стоимости чистых активов фонда в ₽, одной линией, без
    сравнения с чем-либо;
- интервалы **1М / 3М / 6М / 1Г / YTD / Всё**;
- обе линии приведены к **0 %** на старте выбранного интервала — сравнение
  динамики доходности «в лоб»;
- индекс выравнивается по торговым дням фонда: у MCFTR есть значения в отдельные
  праздничные дни, когда УК не считает СЧА, — на график берутся только общие
  даты, поэтому число точек у фонда и индекса совпадает (сырая таблица индекса в
  БД при этом остаётся полной);
- crosshair + тултип с обоими значениями; в конце каждой линии — **кружок-маркер
  и крупная цветная подпись значения**;
- скруглённый шрифт, вертикальная и горизонтальная сетка, жирная нулевая линия,
  ось в формате `30,00%` (запятая, 2 знака);
- **логотип фонда** в шапке и бледным водяным знаком за графиком;
- блок стат (доходность фонда, индекса и их разница);
- кнопка **Таблица** — все значения текстом (доступность);
- светлая/тёмная тема (авто по системе + переключатель).

Палитра — из дизайн-системы data-viz: синий = фонд, оранжевый = индекс
(CVD-safe пара).

### Логотип

Логотип встраивается в `chart.html` при генерации из файла `logo.png` (лежит
рядом; сжатый растр 512×512, отрендерен из исходного `.svg` фонда). Чтобы
заменить логотип — положи свой `logo.png` в эту папку и перегенерируй график
(`python3 build_chart.py`). Если `logo.png` нет — страница строится без логотипа.

> Скруглённый шрифт использует системный `ui-rounded` (SF Rounded) — он виден в
> Safari; в Chrome при отсутствии Nunito будет обычный system-ui. Нужен
> одинаковый вид везде — можно вшить шрифт Nunito, скажи.
