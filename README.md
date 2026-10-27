# MJ

An AI-powered electronics store built with Django, with an Apple-inspired design and marketplace features
like Amazon or Flipkart. Customers browse and buy products, chat with an AI shopping assistant and raise
support tickets. Support agents and administrators work from a dashboard.

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

**Support**: help center with FAQs, a guided "raise a ticket" wizard (issue → order → details and photos),
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
   ├── JSON endpoints: /search/suggest/, /cart/add/, /wishlist/…/toggle/, /assistant/chat/
   │
   ├── Database (SQLite in development, PostgreSQL in production) via the Django ORM
   ├── AI assistant → providers.py → Claude / OpenAI-compatible API / local Ollama, or rules
   ├── Email (console in development, SMTP in production)
   └── Media files (product photos, ticket photos) in media/
```

Administrators can check every component at **Dashboard → System**, which shows the database, AI model, email,
payments, storage and cache, and whether each one is live, in development mode or simulated.

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

## Deploying to Vercel

Import the GitHub repo in Vercel; it detects Django automatically. On Vercel (`VERCEL=1`) the app turns debug
off, accepts `*.vercel.app` hosts, serves CSS/JS with WhiteNoise and serves the product photos in `media/products`.

In Vercel → Project → Settings → Environment Variables, set:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | A long random string: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DATABASE_URL` | A Postgres URL, e.g. from Neon (Vercel → Storage → Neon). Optional, see below. |
| `ANTHROPIC_API_KEY` (or another provider's key) | Optional: powers the AI assistant. Ollama can't run on Vercel. |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Only for a custom domain: `shop.example.com` and `https://shop.example.com` |

**Without `DATABASE_URL`** the site runs on a demo copy of the store (`deploy/demo.sqlite3`, copied to `/tmp`
when an instance starts). It works straight away, but sign-ups, orders and tickets are lost whenever Vercel starts
a new instance, and the demo accounts' passwords are public.

**With `DATABASE_URL`**, data is permanent. Set up the database once from your computer:

```bash
DATABASE_URL='postgresql://...' python manage.py migrate
DATABASE_URL='postgresql://...' python manage.py seed_store --no-users --no-images   # products only
DATABASE_URL='postgresql://...' python manage.py createsuperuser                     # your admin account
```

Run `migrate` the same way after pulling changes that add migrations. Photos uploaded on Vercel (ticket
photos, new product photos) don't survive a new instance; use object storage such as Vercel Blob or S3 for those.
To rebuild the demo database, run `migrate` and `seed_store` against an empty SQLite file and save it as
`deploy/demo.sqlite3`.

## Before deploying elsewhere

- Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS` (and `DJANGO_SERVE_MEDIA=1` or a web
  server for `/media/`).
- Use PostgreSQL (`DATABASE_URL`) instead of SQLite, a real email backend and persistent storage for uploaded photos.
- Configure a shared cache (for example Redis) so the chat rate limit applies across server processes.
- Replace the simulated payment gateway and verify payments with the provider's webhooks.
