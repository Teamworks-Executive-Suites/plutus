#!.venv/bin/python
"""Dev-only: serve just the /bot/* endpoints against the real Firestore.

    .venv/bin/python scripts/dev_bot_server.py

Why not `uvicorn app.main:app`: app.main's lifespan starts the production
background tasks — auto_complete_and_notify, payouts, transaction processing —
which WRITE to the live database. The bot endpoints are read-only; running them
should not also run the billing machinery. This mounts the router alone.

Credentials come from plutus/.env (g_private_key et al), same as production.
"""

import sys
from pathlib import Path

# The repo root, so `app` imports resolve when this is run as a script from
# anywhere. Saves needing PYTHONPATH=. on every invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app.bot.views import bot_router  # noqa: E402

app = FastAPI(title='plutus bot (dev)')
app.include_router(bot_router)

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000, log_level='info')
