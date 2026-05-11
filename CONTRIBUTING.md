# Contributing to ModBot

## Development Workflow

### Branches

- `main` is the production branch — it is always deployable
- Create short-lived feature branches from `main`: `feat/description`, `fix/description`, `chore/description`
- No direct commits to `main` except emergency hotfixes
- All changes land via pull request

### Commit Format

Use conventional commits:

| Prefix     | When to use                                    |
| ---------- | ---------------------------------------------- |
| `feat:`    | New feature                                    |
| `fix:`     | Bug fix                                        |
| `test:`    | Adding or updating tests                       |
| `docs:`    | Documentation changes                          |
| `chore:`   | Maintenance, dependencies, tooling             |
| `refactor:` | Code restructuring without behavior change    |
| `perf:`    | Performance improvement                        |
| `ci:`      | CI/CD pipeline changes                         |

### Pull Request Checklist

Every PR must include:

- **Summary** — what the change does
- **Reason** — why it's needed
- **Testing** — how it was tested, with evidence
- **Risk** — what could go wrong, blast radius
- **Rollback Plan** — how to undo if it breaks

Use the PR template at `.github/pull_request_template.md`.

### Before Pushing

```bash
ruff check .           # No lint errors
ruff format --check .  # Code is formatted
pytest -q              # All tests pass
docker compose config --quiet  # Compose file is valid
```

### CI Pipeline

GitHub Actions runs on every PR and push to `main`:

- `lint` — ruff check
- `format` — ruff format check
- `unit` — pytest (non-integration)
- `integration` — pytest with integration markers
- `miniapp-modbot-build`, `miniapp-admin-build`, `dashboard-build` — frontend builds
- `compose-config` — docker compose config validation
- `docker-build` — image build validation
- `migration-check` — alembic schema validation

All checks must pass before merging.

---

## Code Standards

### Python

- Python 3.11+
- Ruff for linting and formatting (line length: 100)
- Pydantic Settings for configuration
- SQLAlchemy 2.0+ with async sessions
- All new features need tests

### TypeScript / Frontend

- Strict TypeScript where configured
- Components follow existing patterns in `miniapps/` and `dashboard/`
- Builds must succeed in CI

### Database Migrations

- Use Alembic for all schema changes
- Every migration must be reversible (include `downgrade()`)
- Test migrations locally before pushing:
  ```bash
  alembic upgrade head
  alembic downgrade -1
  alembic upgrade head
  ```

---

## Security

### Never commit:

- `.env` files or any environment-specific configuration
- Secrets, API keys, tokens, or credentials
- Telegram session files (`.session`, `.session-journal`)
- Private keys, certificates, or credentials files
- Production logs or database dumps

### Security Checklist

- [ ] No secrets in code or comments
- [ ] Environment variables accessed through `Settings` (pydantic-settings)
- [ ] All secrets in `.env` (which is in `.gitignore`)
- [ ] External API calls use HTTPS
- [ ] User input is validated and sanitized

---

## Testing

### Running Tests

```bash
pytest -q                    # All non-integration tests
pytest -q -m integration     # Integration tests (require Redis)
pytest --cov=bot tests/      # With coverage
```

### Writing Tests

- Place test files in `tests/` matching the module being tested
- Use `pytest-asyncio` for async tests (`asyncio_mode = "auto"`)
- Mark integration tests with `@pytest.mark.integration`
- Use `testcontainers` for container-backed integration tests

---

## Getting Help

- Check `.env.example` for required environment variables
- See `README.md` for architecture overview and setup
- Review `CODEOWNERS` for module ownership

---

## Definition of Done

A feature is done when:

1. Code passes `ruff check .` and `ruff format --check .`
2. All tests pass (`pytest -q`)
3. New tests cover the change
4. CI pipeline is green on the PR
5. PR is reviewed and approved
6. Database migrations are tested up/down
7. Documentation is updated (if applicable)
