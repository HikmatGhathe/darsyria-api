# DarSyria API

The backend for **DarSyria**, a full-stack, trilingual real-estate marketplace
connecting real-estate companies in Syria with the Syrian diaspora in Europe.
This repo is the **FastAPI service**; the web frontend lives in
**[darsyria](https://github.com/HikmatGhathe/darsyria)** (Next.js).

**New contributor? Start with [ARCHITECTURE.md](ARCHITECTURE.md).** It explains
the request lifecycle, module boundaries, database relationships, migrations,
providers, and runtime topology. The
[full-system guide](https://github.com/HikmatGhathe/darsyria/blob/main/ARCHITECTURE.md)
shows how this API connects to the frontend.

---

## What it does

A REST API powering listings, search, messaging, trust & safety, verification,
invoicing, and an AI assistant:

- **Listings & search** — CRUD, image upload/processing to Cloudflare R2
  (EXIF-stripped, resized), structured governorate + geo-coordinates, and a
  filtered/sorted/paginated browse backed by shared query helpers.
- **Auth** — passwordless magic-link + Google OAuth, JWT access tokens in
  httpOnly cookies with rotating refresh tokens.
- **Private enquiries** — buyer-owned web threads, localized seller email,
  signed inbound-reply webhooks, delivery state, and response analytics without
  exposing either party's email address.
- **Trust & safety** — user reporting, admin moderation, and two-track
  **verification** (company business docs + per-listing ownership docs) stored
  in a private bucket and served to admins via short-lived **presigned URLs**.
- **Monetization** — per-listing **invoices** generated on publish, gated by a
  runtime admin "payment required" flag, with a provider-agnostic
  `confirm_paid` seam for adding Stripe/card webhooks later.
- **AI assistant** — retrieval-augmented chat over a Syrian real-estate
  knowledge base using **pgvector** similarity search.
- **Ops & compliance** — IP-based rate limiting on abuse-prone endpoints,
  Sentry error monitoring, a daily saved-search digest scheduler, and GDPR data
  export / account erasure.

## Tech stack

- **Python · FastAPI · Uvicorn**
- **SQLAlchemy · Alembic** (migrations run automatically on container start)
- **PostgreSQL 16 + pgvector** · **Pydantic v2**
- **fastembed** (multilingual embeddings) · **slowapi** (rate limiting)
- **boto3 → Cloudflare R2** (object storage) · **Resend** (email)
- **Sentry** · **Docker Compose + Caddy** (automatic HTTPS)

## Architecture In One Minute

1. Browser client components call the public API through Caddy.
2. Next.js Server Components call the same API over the private Compose
   network and forward the browser's auth cookies.
3. FastAPI validates the request, resolves a request-scoped SQLAlchemy session,
   enforces authorization, and runs the owning router/service.
4. Only FastAPI accesses PostgreSQL, pgvector, R2, Resend, Google OAuth, and the
   configured LLM provider.
5. Alembic migrations run before Uvicorn starts in the API container.

Read **[ARCHITECTURE.md](ARCHITECTURE.md)** for diagrams, the router and table
maps, transaction boundaries, provider behavior, and a backend change guide.

## Project layout

```
app/
  main.py            # FastAPI app, router wiring, lifespan jobs
  config.py          # environment-backed settings
  database.py        # SQLAlchemy engine and request sessions
  dependencies.py    # user/admin authentication dependencies
  models/            # SQLAlchemy models
  schemas/           # Pydantic request/response models
  routers/           # HTTP endpoints grouped by domain
  services/          # domain logic and external-provider adapters
alembic/             # migrations
tests/               # focused behavior and regression tests
ARCHITECTURE.md       # API and database architecture
docs/launch-runbook.md   # production go-live checklist
```

## Running locally (Docker Compose)

```bash
cp .env.example .env        # fill in DB, JWT/secret keys, R2, Resend, etc.
docker compose up -d        # Postgres + API; migrations run on boot
curl http://localhost:8000/health
# interactive API docs: http://localhost:8000/docs
```

Production deploy (single VM, one command, automatic HTTPS via Caddy) is
documented in **[docs/launch-runbook.md](docs/launch-runbook.md)**.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — API layers, request lifecycle, database,
  providers, jobs, deployment, and change guide.
- [Full-system architecture](https://github.com/HikmatGhathe/darsyria/blob/main/ARCHITECTURE.md)
  — browser, Next.js, API, database, and production network together.
- [docs/launch-runbook.md](docs/launch-runbook.md) — production configuration,
  DNS, email, migrations, backups, and release checks.
- [Buyer-seller enquiry architecture](https://github.com/HikmatGhathe/darsyria/blob/main/docs/architecture/buyer-seller-enquiry-email-relay.md)
  — relay states, privacy, webhook processing, and analytics.
