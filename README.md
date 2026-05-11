# ModBot — Telegram Group Moderation Bot

ModBot is a self-hosted Telegram bot for automated group moderation, AI-powered
spam detection, FAQ auto-answering, member management, automation tasks, daily
summaries, and paid subscription access control.

---

## Architecture

```
                       ┌──────────────────────┐
                       │   Telegram Bot API    │
                       └──────────┬───────────┘
                                  │
               ┌──────────────────┼──────────────────┐
               ▼                  ▼                  ▼
       ┌───────────┐    ┌──────────────┐    ┌──────────────┐
       │  Bot (aiogram)  │  Worker (dramatiq) │  Agent Worker  │
       │  - commands     │  - moderation     │  (Telethon)   │
       │  - handlers    │  - analytics     │  - scraping   │
       │  - plugins     │  - summaries     │  - broadcasts │
       └───────┬──────────┘    └──────┬───────┘    └──────┬───────┘
               │                      │                    │
               └──────────────────────┼────────────────────┘
                                      │
                          ┌───────────┴──────────┐
                          │   PostgreSQL + Redis  │
                          └───────────┬──────────┘
                                      │
                          ┌───────────┴──────────┐
                          │   FastAPI Backend     │
                          │   - REST API          │
                          │   - Dashboard API     │
                          │   - WebApp serving    │
                          └───────────┬──────────┘
                                      │
               ┌──────────────────────┼──────────────────┐
               ▼                      ▼                  ▼
       ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
       │  Browser       │    │  ModBot Miniapp│    │  Admin Miniapp│
       │  Dashboard     │    │  (Telegram)    │    │  (Telegram)   │
       └──────────────┘    └──────────────┘    └──────────────┘
```

---

## Quickstart

### Prerequisites

- Docker and Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Setup

```bash
# Clone the repository
git clone <repo-url> modbot
cd modbot

# Copy environment template and edit
cp .env.example .env
# Edit .env with your bot token and configuration

# Start all services
docker compose up -d
```

The bot will be running and the dashboard available at:

| Service             | URL                        |
| ------------------- | -------------------------- |
| Backend API         | `http://localhost:8001`    |
| Browser Dashboard   | `http://localhost:5174`    |
| Admin Miniapp       | `http://localhost:5173`    |
| ModBot Miniapp      | `http://localhost:5177`    |

### Running Without Docker (Dev)

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Start PostgreSQL and Redis (or use Docker just for infra)
docker compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start the bot
BOT_APP_KIND=admin python -m bot.main

# Start the API server (separate terminal)
uvicorn bot.dashboard.api.main:app --host 0.0.0.0 --port 8001 --reload

# Start the worker (separate terminal)
dramatiq bot.workers.tasks
```

---

## Development

### Directory Structure

```
├── bot/                    # Python backend package
│   ├── main.py             # Bot entry point
│   ├── config.py           # Settings (pydantic)
│   ├── core/               # Event bus, plugin manager, runtimes
│   ├── db/                 # SQLAlchemy models and session
│   ├── handlers/           # Telegram message/command handlers
│   ├── services/           # Business logic services
│   ├── ai/                 # AI moderation providers
│   ├── moderation/         # Moderation engine
│   ├── agents/             # Telethon-based userbot agents
│   ├── automation/         # Task automation engine
│   ├── plugins/            # Bot plugins (anti-links, FAQ, etc.)
│   ├── faq/                # FAQ auto-answer system
│   ├── summaries/          # Daily admin summaries
│   ├── workers/            # Dramatiq background workers
│   ├── utils/              # Encryption, i18n, logging, etc.
│   └── dashboard/api/      # FastAPI REST + static serving
├── miniapps/
│   ├── modbot/             # Telegram WebApp miniapp (React)
│   ├── admin/              # Admin miniapp (React)
│   └── shared/             # Shared TypeScript package
├── dashboard/              # Browser dashboard SPA (React)
├── shared/                 # Shared design tokens
├── alembic/                # Database migrations
├── tests/                  # Pytest test suite
├── scripts/                # Utility scripts
└── docker/                 # Frontend Dockerfiles
```

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run specific test file
pytest tests/test_moderation_actions.py

# Run with coverage
pytest --cov=bot tests/
```

### Frontend Development

```bash
# ModBot miniapp
cd miniapps/modbot && npm install && npm run dev

# Admin miniapp
cd miniapps/admin && npm install && npm run dev

# Browser dashboard
cd dashboard && npm install && npm run dev
```

---

## Deployment

### Standalone Deployment

```bash
# Build and start all services
docker compose up -d --build
```

### Deploy Alongside Existing combot Infrastructure

If you have an existing combot deployment with a shared `combot_default`
network, use the deploy overlay:

```bash
cp .env.example .env.deploy
# Edit .env.deploy with production values

docker compose \
  -f docker-compose.yml \
  -f docker-compose.deploy.yml \
  up -d --build migrate bot worker agent_worker backend
```

This connects to the existing `combot_default` network for shared
PostgreSQL and Redis.

---

## CI / CD

GitHub Actions run on:
- **pull_request** to `main`
- **push** to `main`
- **workflow_dispatch** (manual)

### Required Jobs

| Job                     | Purpose                            |
| ----------------------- | ---------------------------------- |
| `lint`                  | Ruff code quality                  |
| `format`                | Ruff format check                  |
| `unit`                  | Python unit tests                  |
| `integration`           | Container-backed integration tests |
| `miniapp-modbot-build`  | ModBot miniapp frontend build      |
| `miniapp-admin-build`   | Admin miniapp frontend build       |
| `dashboard-build`       | Browser dashboard build            |
| `compose-config`        | Docker Compose config validation   |
| `docker-build`          | Docker Compose image build         |
| `migration-check`       | Alembic schema validation          |

---

## Branch Protection Recommendations

Configure the following in your GitHub repository settings
(Settings → Branches → Branch protection rules → Add rule for `main`):

### Required Settings

| Setting                        | Value    |
| ------------------------------ | -------- |
| Require a pull request before merging | `true` |
| Require approvals              | `1`      |
| Require status checks to pass  | `true`   |
| Require branches to be up to date | `true` |
| Do not allow bypassing the above settings | `true` |
| Allow force pushes             | `false`  |
| Allow deletions                | `false`  |

### Required Status Checks

Select the following checks:

- `lint`
- `format`
- `unit`
- `integration`
- `miniapp-modbot-build`
- `miniapp-admin-build`
- `dashboard-build`
- `compose-config`
- `docker-build`
- `migration-check`

These ensure every merge to `main` passes all quality gates.

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable              | Description                          |
| --------------------- | ------------------------------------ |
| `ADMIN_BOT_TOKEN`     | Telegram bot token from BotFather    |
| `DATABASE_URL`        | PostgreSQL connection string         |
| `REDIS_URL`           | Redis connection string              |
| `SESSION_ENCRYPTION_KEY` | Key for encrypting agent sessions |
| `TELEGRAM_API_ID`     | Telegram API ID (for agent accounts) |
| `TELEGRAM_API_HASH`   | Telegram API hash (for agent accounts) |
| `BOT_OWNER_IDS`       | Comma-separated Telegram user IDs    |

---

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development workflow, commit format, security guidelines, and testing instructions.

Module ownership is defined in [.github/CODEOWNERS](./.github/CODEOWNERS).

---

## License

Proprietary. All rights reserved.
