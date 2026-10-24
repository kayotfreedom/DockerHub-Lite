# 🐳 DockerHub Lite

Веб-панель для работы с GitHub-репозиториями и эмуляции Dockerfile **без Docker**.  
Позволяет искать репозитории на GitHub, клонировать их, просматривать файлы, устанавливать зависимости через `pip` и выполнять инструкции `Dockerfile` и `.sh`-скрипты в реальном времени.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## ✨ Возможности

- 🔍 **Поиск репозиториев на GitHub** — с описанием, звёздами, языком и датой обновления.
- 📦 **Клонирование через `git`** — с обработкой ошибок (DNS, доступ, таймауты).
- 📂 **Просмотр репозитория** — список файлов, содержимое, Git-информация (ветка, коммит, remote).
- 🐳 **Эмуляция Dockerfile без Docker**:
  - `FROM` — фиксируется, создаёт папку стадии (`_stage_<name>`) для `AS`.
  - `RUN` — выполняет безопасные команды (`mkdir`, `echo`, `cd`, `ls`, `touch`, `cp`, `mv` и т.д.) в папке репозитория.
  - `COPY` / `ADD` — копирует файлы, распаковывает архивы (`.tar`, `.tar.gz`, `.zip`), поддерживает wildcard и `--from=<stage>`.
  - `WORKDIR`, `ENV`, `SHELL`, `EXPOSE`, `VOLUME`, `USER` — парсятся и применяются.
  - `ENTRYPOINT` + `CMD` — объединяются как в Docker, выполняется финальная команда.
  - `--target <stage>` — выбор целевой стадии многоэтапной сборки.
- 📜 **Запуск `.sh`-скриптов**:
  - Автофикс CRLF (Windows → LF).
  - Проверка синтаксиса `bash -n`.
  - Fallback `python3` → `python` при ошибке.
- 📦 **Установка зависимостей**:
  - Поштучная установка пакетов из `requirements.txt`.
  - Автоигнор проблемных пакетов (ошибки сборки wheel) с попытками `--only-binary` и `--no-deps`.
  - Стриминг логов `pip` в реальном времени.
- 🟢 **Long-running процессы** — если процесс живёт и вывел маркер (`Bot started`, `Listening on` и т.п.), он остаётся работать в фоне. Кнопка «Остановить».
- 📋 **Логи в реальном времени** через SSE — консоль на отдельной вкладке, прокручивается только тело консоли.
- 🗂 **История операций** — клонирование, сборка, установка, удаление.

---

## 🚀 Быстрый старт

### Требования

- **Python 3.11+**
- **Git** (в `PATH`)
- **bash** — Git Bash, WSL или MSYS2 (для `.sh`-скриптов)
- Опционально: **Node.js**, **.NET**, **Java** — если хотите выполнять соответствующие `CMD`

### Установка

```bash
git clone https://github.com/your-username/dockerhub-lite.git
cd dockerhub-lite

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### Запуск

```bash
python main.py
```

Откройте [http://127.0.0.1:8000](http://127.0.0.1:8000).

> ⚠️ При запуске `python main.py` сервер слушает `0.0.0.0:8000` — доступен по сети.  
> Если нужен только локальный доступ, замените `host="0.0.0.0"` на `host="127.0.0.1"`.

---

## 🧱 Структура проекта

```
dockerhub-lite/
├── main.py                 # точка входа, FastAPI app + роутеры
├── run.py                  # точка входа для .exe (PyInstaller)
├── config.py               # константы, regex, пути (RESOURCES_DIR, DATA_DIR)
├── models.py               # Pydantic-модели
├── utils.py                # decode_bytes, make_env, find_bash, is_text_file
├── history.py              # история операций
├── dockerfile_parser.py    # парсинг Dockerfile, подстановка $VAR
├── runner.py               # execute_run, execute_cmd, стриминг процессов
├── build.py                # логика сборки Dockerfile
├── install.py              # логика установки зависимостей
├── archives.py             # распаковка tar/zip
├── crlf.py                 # CRLF-фикс, python3→python
├── routes/
│   ├── pages.py            # GET /
│   ├── repos.py            # /api/search, /api/clone, /api/repos/*
│   ├── builds.py           # /api/build/start, SSE логи
│   ├── installs.py         # /api/install-deps/start, SSE логи
│   ├── scripts.py          # /api/run-script
│   ├── history_routes.py   # /api/history, /api/stats
│   └── stop.py             # /api/stop
├── templates/
│   └── index.html
├── static/
│   └── style.css
├── requirements.txt
└── build.bat               # скрипт сборки .exe для Windows
```

---

## 📖 Как пользоваться

### 1. Поиск и клонирование

1. Откройте вкладку **Поиск**.
2. Введите запрос (например, `python fastapi`) и нажмите **Найти**.
3. У нужного репозитория нажмите **Клонировать** — он появится во вкладке **Репозитории**.

### 2. Сборка

1. Откройте вкладку **Репозитории** → **Открыть** на нужном репозитории.
2. Нажмите **🔨 Собрать** — откроется вкладка **Консоль**, где в реальном времени выполняются инструкции `Dockerfile`.
3. Если в логах появилось `⚠️ Обнаружены отсутствующие зависимости!` — нажмите **📦 Установить зависимости** внизу консоли.
4. После установки `CMD` запустится автоматически.

### 3. Запуск `.sh`-скриптов

1. В деталях репозитория найдите блок **📜 Shell-скрипты**.
2. Нажмите **▶** — скрипт выполнится через bash, логи появятся в консоли.

### 4. Остановка процессов

Если в логах появилось `🟢 Процесс оставлен работать в фоне` — процесс живёт.  
Чтобы его остановить, нажмите **Остановить** (или удалите репозиторий — процесс убьётся автоматически).

---

## 🖥️ Сборка `.exe` (Windows)

Требуется **PyInstaller**:

```bash
pip install pyinstaller
```

Запустите `build.bat` из корня проекта. Он создаст `C:\DockerHubLiteTemp` и `C:\DockerHubLiteTemp\FIles` и выполнит:

```bat
pyinstaller --onefile --name DockerHubLite ^
  --runtime-tmpdir "C:\DockerHubLiteTemp" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import fastapi.openapi.utils ^
  --hidden-import httpx ^
  --hidden-import dockerfile ^
  run.py
```

Готовый `.exe` появится в `dist\DockerHubLite.exe`.

### Где хранятся данные

| Что | Где |
|---|---|
| Ресурсы PyInstaller (`templates`, `static`, библиотеки) | `C:\DockerHubLiteTemp\_MEIxxxxxx` (удаляется при закрытии) |
| Данные (`repos/`, `history.json`) | `C:\DockerHubLiteTemp\FIles\` (не удаляется) |

Папки создаются автоматически при первом запуске (если есть права на `C:\`).

> 💡 Если прав на `C:\` нет, замените `DATA_DIR` в `config.py` на `%LOCALAPPDATA%\DockerHubLite\FIles`.

---

## 🔌 API

| Метод | Эндпоинт | Описание |
|---|---|---|
| `GET` | `/` | Главная страница |
| `GET` | `/api/search?q=` | Поиск репозиториев на GitHub |
| `POST` | `/api/clone` | Клонировать репозиторий |
| `GET` | `/api/repos` | Список локальных репозиториев |
| `GET` | `/api/repos/{name}` | Информация о репозитории |
| `GET` | `/api/repos/{name}/file?path=` | Содержимое файла |
| `DELETE` | `/api/repos/{name}` | Удалить репозиторий |
| `POST` | `/api/build/start` | Запустить сборку |
| `GET` | `/api/build-log/{name}` | SSE-поток логов сборки |
| `POST` | `/api/install-deps/start` | Запустить установку зависимостей |
| `GET` | `/api/install-deps/log/{queue_key}` | SSE-поток логов `pip` |
| `POST` | `/api/run-script` | Выполнить `.sh`-скрипт |
| `POST` | `/api/stop` | Остановить long-running процесс |
| `GET` | `/api/history` | История операций |
| `GET` | `/api/stats` | Статистика |

---

## 🧪 Пример Dockerfile

```dockerfile
FROM python:3.11 AS builder
WORKDIR /app
RUN mkdir -p /app/src
COPY app.py /app/src/
RUN echo "build done" > /app/build.txt

FROM python:3.11
ENV APP_HOME=/app
WORKDIR $APP_HOME
COPY --from=builder /app/src /app/src
ADD archive.tar.gz /app/data/
EXPOSE 8080
USER appuser
CMD ["python", "src/app.py"]
```

Что сделает DockerHub Lite:

- Создаст `_stage_builder/` и `app/`.
- Выполнит `mkdir -p <repo>/app/src`, `echo "build done" > <repo>/app/build.txt`.
- Скопирует `app.py` в `app/src/`.
- Распакует `archive.tar.gz` в `app/data/`.
- Запустит `python src/app.py` из `app/` (если файл существует).

---

## 🐛 Известные ограничения

- **Нет изоляции файловой системы, сети и процессов** — как в настоящем Docker.
- **`FROM` не загружает образы** — базовый образ не скачивается, эмулируется только структура стадий.
- **`bash` обязателен** для `.sh` — на Windows нужен Git Bash или WSL.
- **`.exe` требует Git и bash в `PATH`** — они не упаковываются PyInstaller.
- **Job Objects работают только на Windows** — на Linux/macOS ограничение памяти не применяется.

---

## 📝 Лицензия

MIT. См. [LICENSE](LICENSE).

---

