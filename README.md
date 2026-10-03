# DevSecOps To-Do App

A small to-do list application built to demonstrate a security-focused CI/CD pipeline. The app itself is a Python FastAPI service with a database, user authentication, and a web frontend. The interesting part is the automated checks around it: linting, tests, dependency auditing, static analysis, container scanning, and dynamic security testing run on every push.

## Features

- **To-do management:** create, complete, filter, and delete tasks
- **User accounts:** register and sign in with a username and password; each user only sees their own tasks
- **Persistent storage:** SQLite by default, swappable via `DATABASE_URL`
- **Web frontend:** single-page UI served by the API, with a light/dark theme toggle
- **REST API:** interactive documentation at `/docs`
- **Containerized:** runs as a non-root user with a health check

## Tech stack

| Area | Tools |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy, Uvicorn |
| Auth | Argon2 password hashing, JWT bearer tokens (PyJWT) |
| Frontend | Plain HTML, CSS, and JavaScript (no external dependencies) |
| Database | SQLite (default) |
| Testing | pytest, pytest-cov, httpx |
| Code quality | Ruff (lint and format) |
| Security | pip-audit, Bandit, Trivy, OWASP ZAP |
| CI | GitHub Actions |
| Packaging | Docker |

## Project structure

```
.
├── main.py                  # FastAPI app: models, auth, API routes
├── static/
│   └── index.html           # Frontend (served at /)
├── test_main.py             # API tests
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Test and lint dependencies
├── Dockerfile
├── .dockerignore
└── .github/
    └── workflows/
        └── ci.yml           # CI pipeline
```

## Getting started

### Run locally

Python 3.11 or newer is recommended (CI tests 3.11 through 3.13).

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

python -m pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn main:app --reload
```

Open <http://127.0.0.1:8000> for the app, or <http://127.0.0.1:8000/docs> for the API explorer. On first run the app creates a `todos.db` file next to `main.py`.

### Run with Docker

Generate a secret key, then build and run the container:

```powershell
# PowerShell
$env:SECRET_KEY = docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(32))"
docker build -t todo-api .
docker run --rm -p 8000:8000 -v todo-data:/data -e SECRET_KEY todo-api
```

```bash
# bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
docker build -t todo-api .
docker run --rm -p 8000:8000 -v todo-data:/data -e SECRET_KEY todo-api
```

The `-v todo-data:/data` volume keeps the database between runs. Without it, data is lost when the container is removed.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | random, generated at startup | Key used to sign login tokens. Set it in any real deployment; with a random key, everyone is signed out on each restart and multiple workers will not share sessions. Never commit it. |
| `DATABASE_URL` | `sqlite:///./todos.db` | SQLAlchemy database URL. The Docker image sets it to `sqlite:////data/todos.db`. |

## API

All `/todos` routes require an `Authorization: Bearer <token>` header.

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create an account (`username`, `password`) |
| POST | `/auth/login` | Exchange credentials for an access token |
| GET | `/todos` | List your tasks (`?completed=true` or `false` to filter) |
| POST | `/todos` | Create a task (`title` required, `description` optional) |
| GET | `/todos/{id}` | Get one task |
| PATCH | `/todos/{id}` | Update `title`, `description`, or `completed` |
| DELETE | `/todos/{id}` | Delete a task |

In the `/docs` page, log in via `/auth/login`, then click **Authorize** and paste the token.

## Testing and code quality

```bash
python -m pytest --cov=main --cov-report=term-missing
python -m ruff check .
python -m ruff format --check .
python -m bandit -r . --exclude ./.venv,./test_main.py --severity-level medium
```

Each test runs against its own in-memory database, so tests never touch real data.

## CI pipeline

The workflow in `.github/workflows/ci.yml` runs on pushes and pull requests to `main`, and can also be started manually. Its jobs run in parallel:

| Job | What it does |
|---|---|
| **Lint** | `ruff check` and `ruff format --check` |
| **Test** | `pytest` with coverage on Python 3.11, 3.12, and 3.13 |
| **Dependency audit** | `pip-audit` checks `requirements.txt` for known vulnerabilities |
| **Container scan** | Builds the image and scans it with Trivy; fails on fixable HIGH or CRITICAL findings |
| **SAST** | Bandit static analysis of the Python source |
| **DAST** | Starts the container and runs an OWASP ZAP baseline scan against it; the HTML report is uploaded as a build artifact |

The workflow uses least-privilege token permissions (`contents: read`) and cancels superseded runs.

**Supply-chain choices:** Trivy and ZAP run from their official container images rather than third-party GitHub Actions, following the March 2026 compromise of the `trivy-action` tags. The Trivy image is pinned by digest. The ZAP image uses the official `stable` tag.

## Security notes

- Passwords are hashed with Argon2 and never stored in plain text
- Login failures return identical responses for wrong passwords and unknown usernames, and unknown usernames cost the same time to check, so usernames can't be enumerated
- Tokens are signed JWTs that expire after 60 minutes
- Another user's task returns the same 404 as a nonexistent one
- The frontend inserts all task text with `textContent`, so it is never parsed as HTML
- The container runs as a non-root user, applies OS security updates at build time, and keeps `.env`, `.git`, and local databases out of the image via `.dockerignore`

### Known limitations

- No rate limiting on login attempts
- No HTTPS built in; run behind a TLS-terminating proxy anywhere beyond localhost
- No password reset, refresh tokens, or account deletion
- No database migrations: the app only creates missing tables, so schema changes need a fresh database (or Alembic, once added)
- SQLite suits a single container; use PostgreSQL for multiple replicas
- Login tokens are kept in `sessionStorage`; an httpOnly cookie with CSRF protection would be stronger
- GitHub Actions are referenced by version tag rather than commit SHA

## Roadmap

- Rate limiting on authentication endpoints
- Security headers middleware (to address ZAP findings)
- ZAP API scan authenticated as a test user
- Pin GitHub Actions to commit SHAs and enable Dependabot
- Pin dependency versions with hashes
- Alembic migrations
- Deploy the container to the cloud using OIDC instead of stored credentials