# MJ

An AI-powered electronics store built with Django, with an Apple-inspired design and marketplace features
like Amazon or Flipkart. Customers browse and buy products, chat with an AI shopping assistant and raise
support tickets. Support agents and administrators work from a dashboard.

**Live site: https://mj-shoppingapp.vercel.app** · Health check: https://mj-shoppingapp.vercel.app/health/

## Launch checklist

| Requirement | Where it is |
|---|---|
| Live HTTPS site, 3+ pages, mobile-friendly | Vercel (link above): home, products, product pages, bag, checkout, orders, help center, error codes, tickets. Responsive down to phone width. |
| Chat widget on every page | `templates/assistant/widget.html`, included by `templates/base.html` (also on the 403/404/500 pages) |
| 10+ FAQs in SQL, FAQ page from API | `support.FAQ` table (14 FAQs, editable in Django admin), `GET /api/faqs/`; the help center loads its FAQs from it |
| 8+ error codes in SQL | `support.ErrorCode` table (13 codes such as `PAY-001`, `ORD-001`, `WEB-500`), `GET /api/error-codes/`, page at `/support/error-codes/`. Codes are shown where they happen (payments, checkout, error pages, chat rate limit). |
| Custom 404/500 pages + Ask-assistant button | `templates/404.html`, `templates/500.html` (`myproject/views.py`, with a plain fallback if even that fails), `templates/403.html` |
| Assistant answers FAQs and explains error codes | `assistant/fallback.py` uses `support/lookup.py`; LLMs get the `search_faqs` and `explain_error_code` tools |
| Ticket created when unsure (CRUD) | `support.services.escalate_from_assistant`: questions the assistant can't answer become a ticket for logged-in customers. Tickets: create, read, update, delete in the site and at `/api/tickets/` |
| Chats and feedback stored in MongoDB | `myproject/mongo.py`: every chat turn → `chats`, every 👍/👎 and ticket rating → `feedback` (set `MONGODB_URI`) |
| Keys in env vars, no secrets in GitHub | All keys come from environment variables or the git-ignored `.env`; see `.env.example` |
| Request logs + health check | `myproject/observability.py`: one JSON log line per request with an `X-Request-ID`; `GET /health/`; recent requests on Dashboard → System |
| Extra third-party call with timeout and fallback | India Post PIN code API (`orders/delivery.py`): 3-second timeout, 1-day cache, falls back to a local estimate |
| README with live address and improvements | This file: live address above, improvements at the end |

## Quick start

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_store        # catalog, product photos, demo users, orders and a ticket
python manage.py runserver
```

Open http://127.0.0.1:8000. `seed_store` downloads the product photos from Wikimedia Commons the first time,
so it needs an internet connection (about 7 MB). Run it with `--no-images` to skip them.

### Demo accounts (local development only)

| Role          | Username   | Password         | Try this |
|---------------|------------|------------------|----------|
| Customer      | `customer` | `Customer@12345` | Has a delivered order, an order in transit and an open ticket |
| Support agent | `agent1`   | `Agent@12345`    | Dashboard → Tickets: reply with canned replies and photos, resolve |
| Support agent | `agent2`   | `Agent@12345`    | Second agent for the auto-assignment |
| Administrator | `admin`    | `Admin@12345`    | Everything, including products, prices, stock, users and Django admin |

### Test payments (simulated gateway, no real money)

| Method | Succeeds | Fails |
|--------|----------|-------|
| UPI    | any ID like `you@okbank` | `fail@upi` |
| Card   | `4242 4242 4242 4242` | `4000 0000 0000 0002` (declined), `4000 0000 0000 9995` (insufficient funds) |

Use any future expiry and any CVV. Replace `orders/payments.py` with a real provider (Razorpay, Stripe, ...)
before taking real payments.

## The AI shopping assistant: use any LLM

The chat widget (the "Ask AI" button on every page) works immediately with a built-in rule-based assistant.
Connect a real LLM by setting **one** API key before `runserver`; the store picks it up automatically:

| Provider | What to set |
|----------|-------------|
| Anthropic Claude | `export ANTHROPIC_API_KEY=sk-ant-...` (default model `claude-opus-5-5`) |
| OpenAI | `export OPENAI_API_KEY=sk-...` |
| Google Gemini | `export GEMINI_API_KEY=...` |
| Groq | `export GROQ_API_KEY=...` |
| OpenRouter | `export OPENROUTER_API_KEY=...` |
| Ollama (free, runs on your Mac) | `ollama pull llama3.2 && ollama serve`, then `export LLM_PROVIDER=ollama` |

Optional settings: `LLM_PROVIDER` (`auto`, `anthropic`, `openai`, `gemini`, `groq`, `openrouter`, `ollama`,
`none`), `LLM_MODEL` to pick a model (provider model names change often, so set this to a current one),
`LLM_BASE_URL` for any other OpenAI-compatible server (LM Studio, vLLM) and `ASSISTANT_RATE_LIMIT`
(messages per minute per IP, default 20).

The assistant uses tool calling to search the catalog, compare specs, look up the customer's orders and
tickets, and raise a ticket when the customer agrees. It only quotes prices and order details that come from
the database. If the LLM is unreachable it falls back to the rule-based assistant, and the chat header shows
which one answered.

## Features

**Shopping**: hero carousel, category tiles, deal and top-rated rails, live search suggestions, filters (brand,
price, rating, discount, stock) with counts, sorting, product galleries with zoom, ratings and reviews,
wishlist, recently viewed, PIN code delivery estimate, AJAX add-to-cart, "Buy now", price breakdown with
savings, three-step checkout with UPI or card, order confirmation and a delivery tracker.

**Support**: help center with searchable FAQs (from the API), an error code reference, a guided "raise a ticket" wizard (issue → order → details and photos),
ticket IDs like `TKT-000123`, auto-assignment to the least busy agent, priorities, first-reply deadlines
(4 hours for payment and delivery problems, 24 hours otherwise), conversation threads with photos, internal
notes, canned replies, satisfaction ratings and email notifications (printed to the console in development).

**Colour themes**: six built-in themes: MJ Classic (default; AJIO-inspired slate blue and gold, square corners,
uppercase navigation), Sunset, Ocean (Apple blue), Emerald, Royal (violet) and Midnight (dark mode). Visitors switch with the palette button in the header (remembered per
device). Change the default with `STORE_THEME` in `myproject/settings.py` or the `STORE_THEME` environment
variable. Every colour is a CSS variable in the theme blocks at the top of `static/css/store.css`, so editing a
block or adding a new one restyles the whole site. All themes meet WCAG AA text contrast.

**Logo**: the MJ monogram (the last stroke of the M flows into the J) is `static/img/mj-mark.svg` (also the
favicon); the header version in `templates/includes/logo_mark.html` follows the active theme's colours.

**Design**: Apple-style visual language (SF/Inter type, frosted header, pill buttons, soft shadows), smooth
page transitions (View Transitions API), hover prefetching, scroll animations and a responsive mobile layout.

## How the backend works

MJ is a single Django application: the same server runs the database, business logic, JSON endpoints and pages,
so there is no separate backend to deploy or connect.

```
Browser (HTML pages + fetch() calls)
   │
Django views ── forms & validation ── services (orders/services.py, support/services.py)
   │                                        │
   ├── JSON endpoints: /api/… (FAQs, error codes, tickets, PIN codes), /assistant/chat/, /cart/add/, …
   │
   ├── Database (SQLite in development, PostgreSQL in production) via the Django ORM
   ├── MongoDB: chat transcripts and feedback (optional)
   ├── India Post PIN code API (3 s timeout, local fallback)
   ├── AI assistant → providers.py → Claude / OpenAI-compatible API / local Ollama, or rules
   ├── Email (console in development, SMTP in production)
   └── Media files (product photos, ticket photos) in media/
```

Administrators can check every component at **Dashboard → System**, which shows the database, AI model, email,
MongoDB, payments, storage and cache, whether each one is live, in development mode or simulated, and the
latest requests.

### JSON API

| Endpoint | Methods | What it does |
|---|---|---|
| `/api/faqs/` | GET | FAQs; `?q=refund` to search, `?category=payments` to filter |
| `/api/faqs/<id>/` | GET | One FAQ |
| `/api/error-codes/` | GET | All error codes; `?area=payments` to filter |
| `/api/error-codes/<code>/` | GET | One code, e.g. `/api/error-codes/PAY-001/` |
| `/api/tickets/` | GET, POST | Your tickets (agents see all); create with `{"category", "subject", "description", "order_number"}` |
| `/api/tickets/<code>/` | GET, PATCH, DELETE | Read with messages; edit `subject`/`description` while open, add a `message`, set `status`; delete a ticket nobody has answered yet |
| `/api/pincode/<pin>/` | GET | City, state and delivery date for a PIN code |
| `/health/` | GET | `200` with database, MongoDB and assistant status, `503` if the database is down |

Ticket endpoints use the logged-in session; send the CSRF token in an `X-CSRFToken` header for POST, PATCH and
DELETE.

### MongoDB (chats and feedback)

Create a free cluster at MongoDB Atlas, allow access from anywhere (`0.0.0.0/0`, Vercel has no fixed IP),
create a database user and copy the connection string. Put it in `.env` and in Vercel's environment variables:

```
MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/
MONGODB_DB=mj
```

Every chat turn is stored in the `chats` collection and every 👍/👎 on an assistant reply and every ticket
rating in `feedback`. The SQL database still keeps the chat history the widget shows, so if MongoDB is not set
or is unreachable, chat keeps working: the failure is logged and MongoDB is skipped for a minute.

### Request logs and health

Every request is logged as one JSON line (time, request ID, method, path, status, duration, user, IP) and gets
`X-Request-ID` and `Server-Timing` headers. On Vercel see Project → Logs. Point an uptime monitor (for example
UptimeRobot) at `/health/`.

### Local AI model (free, no API key)

```bash
brew install ollama              # already installed on this Mac
ollama serve                     # keep running (or: brew services start ollama)
ollama pull qwen2.5:3b           # about 2 GB
ollama create mj-assistant -f ollama/Modelfile
```

With Ollama running, the assistant uses the local model automatically (`LLM_PROVIDER=auto`). If Ollama is not
running, the store keeps working with the rule-based assistant. Settings can live in a `.env` file; see
`.env.example`.

## Project structure

| App          | What it does |
|--------------|--------------|
| `accounts`   | Custom `User` with roles (customer / agent / admin), sign-up, profile |
| `catalog`    | Categories, products, photo galleries, reviews, wishlist, search, `seed_store` command |
| `cart`       | Session cart (works for guests, kept after login), save for later |
| `orders`     | Checkout, stock reservation, simulated UPI and card payments, delivery tracking |
| `support`    | Help center, tickets, attachments, SLAs, satisfaction ratings |
| `assistant`  | Chat API, provider selection (`providers.py`), Claude (`llm.py`), OpenAI-compatible (`openai_compat.py`), store tools (`tools.py`), rule-based fallback |
| `dashboard`  | Agent and admin back office: tickets, orders, products, users |

Templates are in `templates/`, styles in `static/css/store.css` and scripts in `static/js/`. When you change
CSS or JS, bump `ASSET_VERSION` in `myproject/settings.py` so browsers load the new files.

## Product photos

Product photos are openly licensed images from Wikimedia Commons (CC0, CC BY and CC BY-SA). Each product page
credits the photographer and licence, and `/photo-credits/` lists them all. Keep these credits if you reuse
the photos. You can upload your own photos per product in the Django admin. The seeded reviews come from demo
accounts and are only there to fill the store for development.

## Running tests

```bash
python manage.py test
```

## Order emails

When a payment succeeds, the customer gets an order confirmation (items, total, address, delivery date and
a tracking link) and everyone in `ORDER_ALERT_EMAILS` gets a "New order" email with a link to the dashboard.
New tickets are emailed to `TICKET_ALERT_EMAILS` (default: the same addresses).
Customers also get an email whenever the order status changes, and ticket updates are emailed too.

Emails are printed to the server console until you set `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`. For
Gmail, turn on 2-Step Verification, create an App Password (Google Account → Security → App passwords) and
put your address and that password in `.env` (locally) and in Vercel's environment variables. Never commit
the password. Dashboard → System shows whether real email is on and who receives alerts, and its **Send test
email** button shows the exact error if Gmail rejects the login.

## Deploying to Vercel

Import the GitHub repo in Vercel; it detects Django automatically. On Vercel (`VERCEL=1`) the app turns debug
off, accepts `*.vercel.app` hosts, serves CSS/JS with WhiteNoise and serves the product photos in `media/products`.

In Vercel → Project → Settings → Environment Variables, set:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | A long random string: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DATABASE_URL` | A Postgres URL, e.g. from Neon (Vercel → Storage → Neon). Optional, see below. |
| `ANTHROPIC_API_KEY` (or another provider's key) | Optional: powers the AI assistant. Ollama can't run on Vercel. |
| `MONGODB_URI` | Optional: MongoDB Atlas connection string for chats and feedback |
| `DJANGO_ADMIN_USERNAME`, `DJANGO_ADMIN_PASSWORD`, `DJANGO_ADMIN_EMAIL` | Your admin account, created on the first start with `DATABASE_URL` |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Gmail address and App Password, to send real emails |
| `ORDER_ALERT_EMAILS`, `TICKET_ALERT_EMAILS` | Who gets "New order" and "New ticket" emails (ticket alerts default to the order list) |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Only for a custom domain: `shop.example.com` and `https://shop.example.com` |

**Without `DATABASE_URL`** the site runs on a demo copy of the store (`deploy/demo.sqlite3`, copied to `/tmp`
when an instance starts). Every Vercel instance gets its own copy, so sign-ins, sign-ups and tickets are not
shared between instances (customers get asked to sign in again) and reset on cold starts. Use it for a quick
look only.

**With `DATABASE_URL`** (one shared Postgres database) everything is permanent and shared. Easiest setup:

1. Vercel → your project → **Storage** → **Create Database** → **Neon (Postgres)** → connect it to the project.
   This adds `DATABASE_URL` for you.
2. Add `DJANGO_ADMIN_USERNAME`, `DJANGO_ADMIN_PASSWORD` and `DJANGO_ADMIN_EMAIL` (your admin account).
3. **Redeploy.** On its first start the app applies migrations, loads the product catalog with photos
   (`deploy/catalog.json`) and creates your admin account (`myproject/vercel.py`). It never overwrites a
   password you change later. The demo logins are hidden on a real database.

Photos uploaded on Vercel (ticket photos, new product photos) don't survive a new instance; use object storage
such as Vercel Blob or S3 for those. To rebuild the demo database, run `migrate` and `seed_store` against an
empty SQLite file and save it as `deploy/demo.sqlite3`.

## Improvements

What I would do next, roughly in order:

1. **Permanent data**: connect Postgres (`DATABASE_URL`) and MongoDB Atlas (`MONGODB_URI`) on Vercel; until
   then the live demo resets when Vercel starts a new instance.
2. **Smarter assistant on the live site**: add an `ANTHROPIC_API_KEY` so Claude answers with tools instead of
   the rule-based assistant, and use the 👍/👎 feedback in MongoDB to find questions to add as FAQs.
3. **Real payments**: Razorpay or Stripe with webhooks instead of the simulated gateway.
4. **Uploads**: store ticket and product photos in Vercel Blob or S3 so they survive redeploys.
5. **Shared cache**: Redis for the chat rate limit and the PIN code cache across instances.
6. **Monitoring**: send the request logs to a log service and alert on `/health/` failures; add error tracking
   (Sentry) with the request ID.
7. **Search**: Postgres full-text or vector search for products and FAQs, so the assistant also understands
   Hindi and spelling variants.

## Before deploying elsewhere

- Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS` (and `DJANGO_SERVE_MEDIA=1` or a web
  server for `/media/`).
- Use PostgreSQL (`DATABASE_URL`) instead of SQLite, a real email backend and persistent storage for uploaded photos.
- Configure a shared cache (for example Redis) so the chat rate limit applies across server processes.
- Replace the simulated payment gateway and verify payments with the provider's webhooks.
