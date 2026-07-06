# DarSyria API

The backend for **DarSyria**, a full-stack, trilingual real-estate marketplace
connecting real-estate companies in Syria with the Syrian diaspora in Europe.
This repo is the **FastAPI service**; the web frontend lives in
**[darsyria](https://github.com/USERNAME/darsyria)** (Next.js).

> Personal/portfolio project.

---

## What it does

A REST API powering listings, search, messaging, trust & safety, verification,
invoicing, and an AI assistant:

- **Listings & search** — CRUD, image upload/processing to Cloudflare R2
  (EXIF-stripped, resized), structured governorate + geo-coordinates, and a
  filtered/sorted/paginated browse backed by shared query helpers.
- **Auth** — passwordless magic-link + Google OAuth, JWT access tokens in
  httpOnly cookies with rotating refresh tokens.
- **Messaging** — buyer ↔ seller conversations with mutual-consent contact
  reveal and email notifications.
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

## Project layout

```
app/
  main.py            # FastAPI app, router wiring, lifespan (digest scheduler)
  models/            # SQLAlchemy models
  schemas/           # Pydantic request/response models
  routers/           # endpoints (properties, auth, conversations, verification,
                     #   billing, admin_*, reports, sellers, chat, sitemap …)
  services/          # r2_storage, email, embeddings, payments, settings, digest
alembic/             # migrations
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
