# Геокешинг-бот v2 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Командная гонка на время по последовательным точкам: код на точке → следующая точка → текст-подсказка финала.

**Architecture:** Репозиторий разносится на `v1/` (текущий бот без изменений) и `v2/` (новый самостоятельный бот). В v2 чистая логика (`game.py`) и база (`db.py`) отделены от хендлеров aiogram и покрыты тестами. Хендлеры тонкие.

**Tech Stack:** Python 3.12, aiogram 3.18, aiosqlite 0.20, python-dotenv, pytest + pytest-asyncio (только dev), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-27-geocaching-v2-design.md`

## Global Constraints

- Все пути v2 — внутри `v2/`; v1 после переноса в `v1/` не меняется ни строкой.
- Тексты для игроков и админки — только русский.
- Радиус: `ACTIVATION_RADIUS_M = 15`, потолок поправки `ACCURACY_BONUS_CAP_M = 10`; без `horizontal_accuracy` поправка 0.
- Свежесть гео: `LOCATION_STALE_S = 120`.
- Троттлинг правки live-сообщения: `LIVE_EDIT_MIN_INTERVAL_S = 4.0`.
- Время в БД — UTC ISO; показ — в `TZ` из `.env`, по умолчанию `Europe/Sofia`.
- Тот же `BOT_TOKEN`, что у v1; база v2 — `v2/data/quest_v2.db`, данные v1 (`data/quest.db` в корне на сервере) не трогаются.
- Никогда не запускать v2 локально с боевым токеном, пока v1 работает на сервере (конфликт getUpdates выбьет прод).
- `t` не использовать как имя переменной (затеняет функцию перевода — правило проекта).

## Review Focus

1. Два участника одновременно вводят верный код → точка засчитана один раз, следующая выдана один раз. Тест: `test_advance_team_only_once` (Task 3).
2. Команда уже финишировала, кто-то шлёт код/гео → бот отвечает подсказкой финала и временем, ничего не ломается. Тест: `test_advance_after_finish_returns_none` (Task 3).
3. Админ удалил точку посреди игры → у команды на последней позиции `current_position > count` трактуется как финиш, а не IndexError. Тест: `test_current_point_after_delete` (Task 3).
4. Код с другим регистром, пробелами, «ё» → принимается. Тест: `test_normalize_code` (Task 2).
5. Гео без `horizontal_accuracy` и гео старше 120 с → строгие 15 м / отказ «обновите гео». Тесты: `test_effective_radius_none`, `test_is_stale` (Task 2).

---

### Task 1: Подтянуть v1 и разнести репозиторий на v1/ и v2/

**Files:**
- Move: все файлы корня (`app.py config.py db.py i18n.py keyboards.py states.py handlers/ utils/ Dockerfile docker-compose.yml requirements.txt .env.example`) → `v1/`
- Modify: `v1/docker-compose.yml` — добавить `name: geocaching_v1`; volume `../data:/data`, `env_file: ../.env` (база и .env v1 остаются в корне — откат v1 одной командой)
- Create: `README.md` (корень): две строки — что в `v1/`, что в `v2/`, как деплоить v2.
- Modify: `.gitignore` — шаблоны `.env`, `data/` должны работать в подпапках (они и так работают без ведущего `/`; проверить).

- [ ] **Step 1:** `git pull --ff-only` (локально отстаёт на 2 коммита). Expected: fast-forward до `98ec7a4`.
- [ ] **Step 2:** `git mv` файлов в `v1/`; локальный `.env` скопировать в `v1/.env` и `v2/.env` (не в git).
- [ ] **Step 3:** Проверка: `cd v1 && python -m py_compile app.py config.py db.py handlers/*.py utils/*.py` — без ошибок.
- [ ] **Step 4:** Commit `chore: move v1 bot into v1/`.

### Task 2: Каркас v2, конфиг и чистая логика игры

**Files:**
- Create: `v2/config.py`, `v2/utils/geo.py` (копия `haversine_m` из v1), `v2/game.py`, `v2/requirements.txt`, `v2/requirements-dev.txt`, `v2/tests/test_game.py`, `v2/pytest.ini` (`asyncio_mode = auto`).

**Interfaces — Produces (`v2/game.py`):**
- `normalize_code(s: str) -> str` — lower, ё→е, убрать все пробельные символы.
- `effective_radius(accuracy: float | None) -> float` — `15 + min(accuracy, 10)`, при `None`/`<=0` → `15`.
- `is_stale(loc_at_iso: str | None, now: datetime) -> bool` — `True`, если `None` или старше 120 с.
- `bearing_deg(lat1, lon1, lat2, lon2) -> float` — начальный азимут 0..360.
- `direction_label(deg: float) -> str` — `"↑ С" "↗ СВ" "→ В" "↘ ЮВ" "↓ Ю" "↙ ЮЗ" "← З" "↖ СЗ"` по секторам 45° с центром на направлении.
- `fmt_dist(m: float) -> str` — `"340 м"` / `"1.2 км"` (как v1).
- `fmt_duration(seconds: int) -> str` — `"1:05:09"` (ч:мм:сс).
- `generate_passwords(n: int, rng: random.Random) -> list[str]` — уникальные `"<слово>-<две цифры>"`, слова из списка ~40 простых русских существительных.
- `rank_results(rows: list[dict]) -> list[dict]` — вход: `{name, started_at, finished_at, taken_count, last_taken_at}`; финишировавшие по `finished_at - started_at` возрастанию, затем остальные по `taken_count` убыванию, затем `last_taken_at` возрастанию; не стартовавшие — в конце.

- [ ] **Step 1: Тесты** в `v2/tests/test_game.py`:
  - `test_normalize_code`: `normalize_code("  Ёлка 12 ") == "елка12"`; `normalize_code("ABC") == "abc"`.
  - `test_effective_radius_none`: `effective_radius(None) == 15`; `effective_radius(0) == 15`.
  - `test_effective_radius_capped`: `effective_radius(4) == 19`; `effective_radius(50) == 25`.
  - `test_is_stale`: `None` → True; 119 с назад → False; 121 с назад → True.
  - `test_direction_label`: `direction_label(0) == "↑ С"`, `direction_label(44) == "↗ СВ"`, `direction_label(350) == "↑ С"`, `direction_label(180) == "↓ Ю"`.
  - `test_bearing_north`: точка севернее → `bearing_deg` ≈ 0 (±1).
  - `test_generate_passwords_unique`: `len(set(generate_passwords(30, random.Random(1)))) == 30`, каждый матчит `^[а-я]+-\d{2}$`.
  - `test_rank_results`: финишировавший за 1 ч выше финишировавшего за 2 ч; оба выше нефинишировавшего с 5 точками; тот выше нефинишировавшего с 3.
  - `test_fmt_duration`: `fmt_duration(3909) == "1:05:09"`.
- [ ] **Step 2:** `cd v2 && pytest tests/test_game.py -v` → FAIL (нет модуля).
- [ ] **Step 3:** Реализовать `game.py`, `config.py` (`TOKEN, ADMINS, DB_PATH="data/quest_v2.db", TZ="Europe/Sofia"` из env + константы из Global Constraints).
- [ ] **Step 4:** `pytest tests/test_game.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(v2): game logic and config`.

### Task 3: База данных v2

**Files:** Create `v2/db.py`, `v2/tests/test_db.py` (фикстура: `DB_PATH` во временный файл через monkeypatch `db.DB_PATH`).

**Schema:**
- `points(id INTEGER PK, position INTEGER NOT NULL, label TEXT, lat REAL, lon REAL, code TEXT)`
- `teams(id INTEGER PK, name TEXT, password TEXT UNIQUE, is_test INTEGER DEFAULT 0, started_at TEXT, finished_at TEXT, current_position INTEGER NOT NULL DEFAULT 1)`
- `members(user_id INTEGER PK, team_id INTEGER, last_lat REAL, last_lon REAL, last_accuracy REAL, last_loc_at TEXT)`
- `team_points(team_id, point_id, taken_at TEXT, taken_by INTEGER, PK(team_id, point_id))`
- `settings(key PK, value)` — `final_hint` по умолчанию `""`.

**Interfaces — Produces:**
- `init_db() -> None`
- Точки: `get_points() -> list[dict]` (по `position`), `get_point(id) -> dict|None`, `add_point(label, lat, lon, code) -> int` (position = max+1), `update_point(id, **fields) -> None` (label/lat/lon/code), `delete_point(id) -> None` (перенумеровать positions 1..n), `move_point(id, delta: int) -> None` (обмен с соседом; на краю — no-op).
- `get_current_point(team: dict) -> dict|None` — точка с `position == team["current_position"]`; `None` = маршрут пройден.
- Команды: `create_teams(n, is_test=False) -> list[dict]` (имена «Команда K» с продолжением нумерации, пароли из `game.generate_passwords`, без коллизий с существующими), `get_team(id)`, `get_team_by_password(pw) -> dict|None` (сравнение через `normalize_code`), `list_teams()`, `rename_team(id, name)`, `delete_team(id)` (удаляет и members, team_points).
- Участники: `join_team(user_id, team_id, now_iso) -> dict` (upsert member; если `started_at IS NULL` — ставит `now_iso`; возвращает команду), `leave_team(user_id)`, `get_member(user_id) -> dict|None`, `get_team_member_ids(team_id) -> list[int]`, `update_member_location(user_id, lat, lon, accuracy, loc_at_iso)`.
- `advance_team(team_id, expected_position, point_id, user_id, now_iso, total_points: int) -> dict|None` — одним `UPDATE teams SET current_position = current_position + 1 [, finished_at = now_iso если expected_position == total_points] WHERE id=? AND current_position=? AND finished_at IS NULL`; при `rowcount == 1` вставить `team_points` и вернуть обновлённую команду, иначе `None`.
- `get_results(include_test=False) -> list[dict]` — строки для `game.rank_results` + `taken: list[{label, taken_at}]`.
- `reset_progress(test_only: bool) -> None` — у затронутых команд `started_at=NULL, finished_at=NULL, current_position=1`, удалить их `team_points`. Участники остаются в командах.
- `get_setting(key) -> str`, `set_setting(key, value)`.

- [ ] **Step 1: Тесты** в `v2/tests/test_db.py`:
  - `test_points_order_and_move`: добавить A,B,C; `move_point(C, -1)` → порядок A,C,B; `move_point(A, -1)` → без изменений.
  - `test_delete_renumbers`: удалить B из A,B,C → positions `[1, 2]`.
  - `test_join_sets_start_once`: первый `join_team` ставит `started_at=t1`, второй участник с `t2` его не меняет.
  - `test_password_lookup_normalized`: `get_team_by_password("  ТИГР-42 ")` находит `тигр-42`.
  - `test_create_teams_unique_passwords`: 2 раза по 10 → 20 уникальных паролей, имена `Команда 1..20`.
  - `test_advance_team_only_once`: два `advance_team(..., expected_position=1, ...)` подряд → первый dict, второй `None`; `team_points` одна строка.
  - `test_advance_last_sets_finished`: при `expected_position == total_points` у команды появляется `finished_at`.
  - `test_advance_after_finish_returns_none`.
  - `test_current_point_after_delete`: команда на позиции 3 из 3, удалили одну точку → `get_current_point` = `None`.
  - `test_reset_test_only`: сброс тестовых не трогает боевую команду.
  - `test_results_exclude_test`.
- [ ] **Step 2:** `pytest tests/test_db.py -v` → FAIL.
- [ ] **Step 3:** Реализовать `db.py` (стиль v1: `async with aiosqlite.connect(DB_PATH)` на каждый вызов; `PRAGMA foreign_keys` не нужен — удаление каскадом руками).
- [ ] **Step 4:** `pytest -v` → всё PASS.
- [ ] **Step 5:** Commit `feat(v2): database layer`.

### Task 4: Хендлеры игрока

**Files:** Create `v2/handlers/player.py`, `v2/keyboards.py` (часть игрока), `v2/states.py` (`PlayerLogin.waiting_password`), `v2/texts.py` (все тексты игрока константами), `v2/app.py` (как v1: `init_db`, admin_router раньше player_router), `v2/tests/test_player_logic.py`.

**Interfaces:**
- Consumes: всё из Task 2 и Task 3.
- Produces (`v2/handlers/player.py`, используется админкой для «играть как игрок»): `player_router`, `async def notify_team(bot, team_id, text, exclude: int|None = None) -> None`, `def render_target(member: dict|None, point: dict) -> str` (чистая функция: название точки, `direction_label` + `fmt_dist`, точность; без гео — «включите трансляцию геопозиции»), `def check_code(member: dict, point: dict, code: str, now: datetime) -> str` возвращает `"ok" | "wrong" | "no_location" | "stale" | "far"` (порядок проверок: код → наличие гео → свежесть → радиус).

**Поведение:**
- `/start`: не в команде → просит пароль (FSM). В команде → текущее состояние (точка или подсказка финала + время).
- Пароль верный → `join_team`, сообщение «Вы в команде X», первая/текущая точка, кнопка «📍 Поделиться геолокацией» + подсказка, как включить трансляцию. Неверный → «Пароль не подходит».
- `/logout` → `leave_team`, снова просит пароль.
- `F.location` (разовая) → `update_member_location`, ответ `render_target`.
- `edited_message F.location` (трансляция) → обновить позицию, править одно сообщение (in-memory `_live_msg[user_id]`, троттлинг 4 с, как в v1); если точка сменилась — слать новое сообщение, а не править старое.
- Любой текст от участника (не команда, не в FSM) = попытка кода → `check_code`:
  - `ok` → `advance_team`; `None` (кто-то опередил) → показать текущее состояние; иначе `notify_team` всем: «✅ Точка N взята (кто — имя)» + следующая точка, либо при финише — подсказка финала + время команды `fmt_duration`.
  - `wrong` → «Код неверный»; `far` → «Вы далеко от точки (N м), подъезжайте ближе»; `stale`/`no_location` → «Обновите геопозицию».
- Команда финишировала → на любое сообщение подсказка финала + время.

- [ ] **Step 1: Тесты** `test_player_logic.py`:
  - `test_check_code_ok_within_radius` (14 м, accuracy None) → `"ok"`.
  - `test_check_code_far_strict` (16 м, accuracy None) → `"far"`.
  - `test_check_code_accuracy_bonus` (22 м, accuracy 8) → `"ok"`.
  - `test_check_code_wrong_first` (неверный код и далеко) → `"wrong"`.
  - `test_check_code_stale` (верно, рядом, 3 мин назад) → `"stale"`.
  - `test_check_code_no_location` → `"no_location"`.
  - `test_render_target_no_location` содержит «трансляц».
- [ ] **Step 2:** `pytest tests/test_player_logic.py -v` → FAIL.
- [ ] **Step 3:** Реализовать.
- [ ] **Step 4:** `pytest -v` → PASS; `python -m py_compile app.py handlers/*.py`.
- [ ] **Step 5:** Commit `feat(v2): player flow`.

### Task 5: Админка

**Files:** Create `v2/handlers/admin.py`, дополнить `v2/keyboards.py`, `v2/states.py` (`AdminPoint.label/coords/code`, `AdminEdit.value`, `AdminTeams.count`, `AdminHint.text`).

**Interfaces:** Consumes Task 3, `player.render_target`. Produces `admin_router`, `is_admin(user_id) -> bool`.

**Меню `/admin`** (паттерн v1: inline-кнопки, `/cancel`, `/myid`):
- 📍 Точки: список по порядку (✅ если есть координаты и код, иначе ⚠️) → карточка: 👁 как видит игрок, ✏️ название, 📍 координаты (гео-пин или текст `lat, lon` — как v1), 🔑 код, ⬆️/⬇️, 🗑 (с подтверждением). ➕ Добавить: название → гео → код.
- 🏁 Финальная подсказка: показать текущую, ввести новую.
- 👥 Команды: список «имя — пароль — позиция/финиш»; «Создать команды» → число → одним сообщением список «команда — пароль» (пароль в `<code>`); карточка команды: переименовать, удалить (подтверждение). «🧪 Тестовая команда» → `create_teams(1, is_test=True)`.
- 📊 Результаты: `rank_results(get_results())` таблицей в `<pre>`, время в `TZ`.
- ♻️ Сброс: «Сбросить игру» (все боевые, подтверждение) и «Сбросить тестовые».
- При правке/удалении/перестановке точек: если есть стартовавшие нетестовые команды — предупреждение в ответе.

- [ ] **Step 1:** Реализовать (логика — в db/game, уже покрыта тестами; тут только UI).
- [ ] **Step 2:** `python -m py_compile handlers/admin.py`; `pytest -v` → PASS.
- [ ] **Step 3:** Commit `feat(v2): admin panel`.

### Task 6: Docker и локальная проверка

**Files:** Create `v2/Dockerfile` (как v1), `v2/docker-compose.yml` (`name: geocaching_v2`, сервис `geocaching_bot_v2`, `DB_PATH=/data/quest_v2.db`, `TZ=${TZ:-Europe/Sofia}`, volume `./data:/data`), `v2/.env.example`.

- [ ] **Step 1:** `cd v2 && docker compose build` → успешно.
- [ ] **Step 2:** `docker compose run --rm geocaching_bot_v2 python -c "import app"` → без ошибок (бот не стартует — только импорт).
- [ ] **Step 3:** Commit `chore(v2): docker`; push в `origin/main` — только с явного разрешения пользователя.

### Task 7: Деплой v2 вместо v1 (с подтверждения пользователя)

Сервер: `ssh -i /Users/Dzmitry_Skrotski/Documents/FUNCKER/BOTs/keys/id_ed25519 -p 7777 funcker@37.27.12.112`, каталог `/home/funcker/tg_en_geocaching_bot` (единственная копия, git на `385dced`, чистый; контейнер `tg_en_geocaching_bot-geocaching_bot-1`; `data/` принадлежит root — читать можно, писать нет). Порядок важен: после `git pull` корневой `docker-compose.yml` исчезнет.

- [ ] **Step 1:** Бэкап: `cp data/quest.db ~/quest.db.bak-$(date +%Y%m%d-%H%M%S)`; `cp .env ~/geocaching.env.bak`.
- [ ] **Step 2:** В корне каталога: `docker compose down` (останавливает v1; данные v1 остаются в `data/`).
- [ ] **Step 3:** `git pull --ff-only`; `cp .env v2/.env` (тот же токен и ADMIN_IDS).
- [ ] **Step 4:** `cd v2 && docker compose up --build -d`; `docker compose logs --tail 20` → «Bot started», без ошибок.
- [ ] **Step 5:** Ручная проверка в Telegram (пользователь или админ): `/admin` → тестовая команда → вход по паролю → гео → ввод кода. Откат: `cd v2 && docker compose down && cd ../v1 && docker compose up --build -d` (v1 смотрит в `../data` и `../.env`).
