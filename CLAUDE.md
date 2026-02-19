# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocChat is a Python FastAPI application (v0.1.0) for document-based chat. Currently in early development with a basic API skeleton.

## Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the dev server
uvicorn app.main:app --reload

# The API docs are at http://localhost:8000/docs
```

## Architecture

- **app/main.py** — FastAPI app entry point. Creates the app instance, registers middleware (request logging), includes routers, and defines the root endpoint.
- **app/core/config.py** — Pydantic Settings-based configuration. Loads from environment variables or `.env` file. The `settings` singleton is imported throughout the app.
- **app/api/** — API route modules. Each module defines an `APIRouter` that gets included in `main.py` with the `/api/v1` prefix.
- **app/models/** and **app/services/** — Placeholder packages (empty, to be built out).

## Key Conventions

- Configuration is centralized via `app.core.config.settings` — always use this rather than reading env vars directly.
- API routes live in `app/api/` as separate router modules, included in `main.py` with `settings.api_prefix` (`/api/v1`).
- Python 3.13 with a local `venv/` virtual environment.
