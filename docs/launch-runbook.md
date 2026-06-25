# DarSyria — Launch Runbook

A practical, ordered checklist to take DarSyria from "works on my machine" to a
public launch for real EU/diaspora users. Tailored to the actual stack:

- **API** — FastAPI (`darsyria-api`), Postgres 16 + pgvector, served by uvicorn.
- **Frontend** — Next.js 16 standalone (`darsyria`), server + client islands.
- **Orchestration** — `darsyria-api/docker-compose.yml` builds and runs all
  three services (postgres, api, frontend).
- **External services** — Resend (email), Cloudflare R2 (image storage),
  Google OAuth (optional login), Sentry (optional error monitoring).

Work top to bottom. The **blocking** items are marked 🔴 — skip one and real
users hit a broken flow.

---

## 1. Accounts & infrastructure you need first

- [ ] A **server / VM** with Docker + Docker Compose (2 vCPU / 4 GB RAM minimum
      — the API downloads a ~1.3 GB embedding model on first boot, cached in a
      named volume thereafter).
- [ ] A **domain** (e.g. `darsyria.com`) with DNS you control.
- [ ] 🔴 **Resend** account + a verified sending domain (see §5 — this gates
      magic-link login and every notification email).
- [ ] **Cloudflare R2** bucket with a public dev/custom URL (listing images).
- [ ] **Google OAuth** credentials, *if* you want Google sign-in (optional;
      magic-link login works without it).
- [ ] **Sentry** project(s), if you want error monitoring (optional; the app
      runs fine with no DSN — see §7).

---

## 2. Secrets to generate (don't reuse dev values) 🔴

Generate fresh, high-entropy values for production:

```bash
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 32   # JWT_SECRET
openssl rand -hex 24   # POSTGRES_PASSWORD
```

Never commit `.env`. Keep these in your host's secret store / a private
`.env` on the server only.

---

## 3. Environment configuration

Two `.env` files. Start from the committed `.env.example` in each repo.

### API — `darsyria-api/.env` 🔴

| Var | Production value | Why it matters |
|---|---|---|
| `APP_ENV` | `production` | **Switches auth cookies to `Secure`** (`cookie_secure` is derived from this). Without it, login cookies won't be sent over HTTPS-only and sessions break. |
| `DATABASE_URL` | (overridden by compose to the `postgres` service) | Leave host value; compose points it at the `postgres` container. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | your values | Must match what compose initializes Postgres with. |
| `SECRET_KEY`, `JWT_SECRET` | from §2 | Session/token signing. |
| `FRONTEND_URL` | `https://darsyria.com` | **Magic-link emails link here.** Wrong value = dead login links. |
| `ALLOWED_ORIGINS` | `https://darsyria.com,https://www.darsyria.com` | CORS allow-list. The browser app's origin must be here or every API call is blocked. |
| `GOOGLE_CLIENT_ID/SECRET` | your values (if used) | Google sign-in. |
| `GOOGLE_REDIRECT_URI` | `https://api.darsyria.com/auth/google/callback` | Must **exactly** match the Authorized redirect URI in Google Cloud Console. |
| `R2_*` (6 vars) | your Cloudflare R2 values | Image upload + serving. |
| `R2_PUBLIC_URL` | your public bucket URL | Also see the Next.js note below. |
| `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_FROM_NAME` | your values | Transactional email. `EMAIL_FROM` must be on the verified Resend domain (§5). |
| `SENTRY_DSN` | (optional) your API DSN | Empty = monitoring off (no-op). |

### Frontend — build args (set on the host before `docker compose build`)

`NEXT_PUBLIC_*` values are **inlined at build time**, so they're passed as
Docker **build args** (already wired in `docker-compose.yml` / `Dockerfile`):

| Var | Production value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.darsyria.com` (the API as the **browser** reaches it) |
| `NEXT_PUBLIC_SITE_URL` | `https://darsyria.com` (canonical / OG / sitemap URLs) |
| `NEXT_PUBLIC_SENTRY_DSN` | (optional) your frontend DSN |

> ⚠️ If you change `NEXT_PUBLIC_*` values you must **rebuild** the frontend
> image — a restart alone won't pick them up.

> ⚠️ The R2 public hostname is hard-coded in `darsyria/next.config.ts`
> (`images.remotePatterns`). If your bucket's public hostname differs from the
> one there, add it, or `next/image` will refuse to load listing photos.

---

## 4. Email deliverability — SPF / DKIM / DMARC 🔴

This is the single most common silent launch failure: magic-link login and
digest emails land in spam, so users "can't log in." In the **Resend
dashboard → Domains**, add your sending domain and create the DNS records it
gives you:

- [ ] **SPF** — a TXT record authorizing Resend to send for your domain.
- [ ] **DKIM** — the CNAME/TXT keys Resend provides (signs your mail).
- [ ] **DMARC** — a `_dmarc` TXT record, start with
      `v=DMARC1; p=none; rua=mailto:you@domain` (monitor), tighten to
      `quarantine`/`reject` later.
- [ ] Domain shows **Verified** in Resend.
- [ ] `EMAIL_FROM` uses this domain (e.g. `no-reply@darsyria.com`).
- [ ] **Test:** send yourself a magic link in production and confirm it lands
      in the inbox (not spam) and the link works.

---

## 5. Database & migrations

- Migrations run **automatically** on API container start
  (`docker-entrypoint.sh` runs `alembic upgrade head` before uvicorn). No manual
  step on deploy.
- [ ] 🔴 **Backups.** Postgres data lives in the `postgres_data` Docker volume.
      Set up a scheduled dump *off the box*:
      ```bash
      docker exec darsyria-postgres pg_dump -U darsyria darsyria \
        | gzip > backup-$(date +%F).sql.gz
      ```
      Cron this daily and ship the file to object storage. **Test a restore
      once** before launch — an untested backup isn't a backup.
- [ ] Confirm the volume is on persistent disk (not ephemeral instance
      storage).

---

## 6. Deploy

- [ ] Put the API and frontend behind a **reverse proxy with TLS** (Caddy,
      Traefik, or nginx + certbot). Suggested routing:
      `https://darsyria.com` → frontend `:3000`,
      `https://api.darsyria.com` → api `:8000`.
      Terminate HTTPS at the proxy. (Compose only exposes plain ports.)
- [ ] On the server:
      ```bash
      cd darsyria-api
      docker compose build      # picks up NEXT_PUBLIC_* build args from env
      docker compose up -d
      ```
- [ ] First boot: the API downloads the embedding model (~1.3 GB) — give it a
      few minutes; it's cached in the `embedding_cache` volume afterward.
- [ ] Health checks pass:
      ```bash
      curl https://api.darsyria.com/health
      curl https://api.darsyria.com/health/db   # database/pgvector/schema OK
      ```

> **Single-replica note:** the daily digest runs on an in-process scheduler at
> 09:00 UTC inside the API. Run **one** API replica, or the digest fires once
> per replica. Fine at launch scale; revisit if you scale out.

---

## 7. Error monitoring (optional but recommended)

Already wired; enable by setting DSNs:

- [ ] API: set `SENTRY_DSN` in `darsyria-api/.env`.
- [ ] Frontend: set `NEXT_PUBLIC_SENTRY_DSN` build arg and **rebuild**.
- [ ] (Optional, for readable stack traces) set `SENTRY_ORG`, `SENTRY_PROJECT`,
      `SENTRY_AUTH_TOKEN` so the frontend build uploads source maps.
- [ ] **Verify delivery:** trigger one test error on each side and confirm it
      lands in the Sentry dashboard. (Init is verified in code; actual delivery
      needs a real DSN + network.)

---

## 8. Legal / compliance (EU)

- [ ] **Impressum** (`/[locale]/impressum`), **Privacy**, **Terms**, and
      **Cookies** pages are present — review their content reflects the real
      operator and is current before launch.
- [ ] Cookie notice renders.
- [ ] Confirm the privacy policy names Resend, Cloudflare R2, Google, and
      Sentry as processors if you enable them.
- [ ] 🔴 **Verification documents** (deeds/IDs/licenses) are sensitive personal
      data and must live in a **private** R2 bucket. Otherwise they sit in the
      main (public-domain) bucket and are reachable if an object key leaks — not
      appropriate for GDPR personal data. Steps:
      1. Cloudflare dashboard → R2 → **Create bucket**, e.g. `darsyria-verification`.
      2. On that bucket: **do NOT** enable public access — no "Public
         Development URL" (`r2.dev`), no custom public domain. Leave it private.
      3. Make sure your R2 API credentials (`R2_ACCESS_KEY_ID` /
         `R2_SECRET_ACCESS_KEY`) can read+write this bucket. If your token is
         scoped to a single bucket, create/repoint a token covering **both** the
         images bucket and this one. `R2_ENDPOINT_URL` is unchanged (account-level).
      4. Set `R2_PRIVATE_BUCKET_NAME=darsyria-verification` in the API `.env` and
         restart the API.
      5. Verify: upload a document, confirm an admin can open it (presigned URL
         loads), and that it is **not** served from the public `*.r2.dev` images
         domain. Admins always read via short-lived presigned URLs regardless.

---

## 9. Pre-launch smoke test (production, real domain) 🔴

Walk the critical path as a real user, on the live site:

1. [ ] Sign up / log in via magic link — email arrives in inbox, link works.
2. [ ] (If enabled) Google sign-in works end to end.
3. [ ] Create a listing with a governorate + a map pin + an uploaded photo →
       it publishes and the photo displays.
4. [ ] Browse, filter by governorate/price, open the listing — map renders.
5. [ ] Message the seller; confirm the seller gets the notification email.
6. [ ] Report a listing; confirm it appears in the admin Reports queue.
7. [ ] Admin: verify a seller, see the "Verified seller" badge.
8. [ ] Check `/ar` renders RTL and prices show correctly.
9. [ ] Rate limits hold (e.g. spamming reports eventually returns HTTP 429).

---

## 10. Launch-day quick checklist

- [ ] 🔴 `APP_ENV=production` (secure cookies)
- [ ] 🔴 `FRONTEND_URL` + `ALLOWED_ORIGINS` = real domain(s)
- [ ] 🔴 Resend domain verified (SPF/DKIM/DMARC); test email lands in inbox
- [ ] 🔴 Fresh `SECRET_KEY` / `JWT_SECRET` / DB password
- [ ] 🔴 Daily DB backup scheduled **and a restore tested**
- [ ] 🔴 TLS in front of both services
- [ ] Frontend rebuilt with prod `NEXT_PUBLIC_*` build args
- [ ] `GOOGLE_REDIRECT_URI` matches Google console (if using Google login)
- [ ] R2 public hostname allowed in `next.config.ts`
- [ ] Sentry DSNs set + delivery verified (if using)
- [ ] `/health` + `/health/db` green
- [ ] Smoke test (§9) passes end to end
