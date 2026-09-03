# Internet Pricing

Internet Pricing is a pricing-focused fork of [General Search](https://github.com/zageabb/general-search). It keeps the same conversation-first interface, live research activity, cited Markdown answers, browser-local chat history, document uploads, settings, and Markdown export while specialising the research workflow for market pricing and budget estimates.

The application is intended for difficult-to-price equipment and project packages where a simple retail search is not enough. It can search public procurement documents, schedules of rates, tender awards, purchase-order benchmarks, OEM technical pages, distributor listings and other relevant public evidence, then compare specification and scope before producing a cited budgetary estimate.

The pricing core works across product types. It selects a deterministic strategy for consumer/retail products, industrial products, HV equipment, services/projects, or a general product, while retaining the same evidence, date, currency-conversion and model-knowledge fallback rules. Because this is a pricing application, a bare recognised product description such as `Lenovo V15 16GB 512GB laptop` is treated as a request to find its price.

## Pricing behaviour

For pricing requests the assistant is instructed to:

- Treat price questions as web-research questions by default.
- Search using the exact equipment/specification plus complementary benchmark searches such as procurement, tender, award, schedule-of-rates and OEM queries.
- Prefer primary and authoritative commercial evidence over SEO pages or generic price aggregators.
- Capture the specification, quantity, scope boundary, source date and currency of each useful benchmark.
- Separate equipment-only supply from erection, testing, commissioning, civils, protection/control, cabling and complete installed-package costs where relevant.
- Compare like-for-like scope before using a benchmark and explain important differences.
- Give low/base/high or reasonable tender ranges when the evidence supports estimation rather than a single false-precision figure.
- If searches return no readable evidence, fall back to model knowledge instead of returning nothing. Any pricing from that fallback is explicitly labelled indicative, not web-verified, and low confidence.
- Clearly label estimates and assumptions and keep externally verifiable price claims tied to citations.
- Preserve the General Search answer presentation: concise Markdown, tables where useful, inline source references and a source list.

Category strategies are deliberately separate:

- Consumer products prioritise exact model/specification retailer listings.
- Industrial products prioritise manufacturer and distributor catalogues, quotations and procurement evidence.
- HV equipment prioritises utility tenders, awards, frameworks and schedules while comparing ratings and scope.
- Services and projects prioritise labour/day rates, schedules of rates, awards, geography and inclusions.
- Other products begin with exact-description supplier, distributor and catalogue searches.

A request such as `Find a price for 400 kV GIS switchgear, 2 incomers 2000 A and 6 feeders 630 A` should therefore trigger searches for current 400/420 kV GIS quotations or procurement benchmarks, comparable bay configurations and OEM technical context, then return a structured budget estimate with source-backed reasoning.

## Web page reading

Internet Pricing keeps the lightweight reader as the default path. Public HTML and PDFs are fetched with bounded HTTP requests first, then structured commerce data, product metadata, tables and visible text are extracted.

For JavaScript-heavy commercial pages, an optional Playwright fallback uses headless Chromium only when a shortlisted retail, industrial or general-product page still has no visible price after the lightweight fetch. The fallback:

- reuses one Chromium process and opens a fresh isolated browser context for each page;
- executes JavaScript and extracts the rendered DOM through the same structured/visible-text parser;
- renders at most three candidate pages per fetch batch by default;
- uses a 15 second navigation timeout by default;
- blocks images, video/media, fonts and common advertising/analytics hosts;
- validates browser requests as public URLs to retain the application's SSRF protections;
- caches successful rendered content through the existing retrieval cache;
- does not pass `--no-sandbox`, so Chromium retains its normal sandbox when the service runs as an unprivileged account;
- does not attempt to bypass logins, CAPTCHAs, bot challenges or other access controls.

HV and service/project procurement pages continue through the lighter HTML/PDF path because browser rendering usually adds cost without improving those sources.

The browser fallback can be tuned with environment variables:

```bash
INTERNET_PRICING_BROWSER_FALLBACK=1       # set 0 to disable
INTERNET_PRICING_BROWSER_MAX_PAGES=3      # clamped to 0..5
INTERNET_PRICING_BROWSER_TIMEOUT_MS=15000 # clamped to 5000..30000
INTERNET_PRICING_BROWSER_SETTLE_MS=1500   # post-load settle, clamped to 0..5000
PLAYWRIGHT_BROWSERS_PATH=/home/zageabb/ollama-chat/playwright-browsers
```

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp settings.example.json settings.json
.venv/bin/python app.py
```

On a new Ubuntu host, Playwright's system libraries may also need to be installed once. Run this with administrator privileges during server provisioning, not from the web application service account:

```bash
sudo .venv/bin/python -m playwright install-deps chromium
```

After Python dependencies are installed on an existing host, `bash deploy/install-browser.sh` installs the compatible Chromium build. The script supports both a project-local `.venv` and this deployment's shared `../venv`; `INTERNET_PRICING_PYTHON` can explicitly override the interpreter. Set the same `PLAYWRIGHT_BROWSERS_PATH` in the application service environment.

Open [http://127.0.0.1:5053](http://127.0.0.1:5053). Set your Ollama URL and model on the Settings page. The active port defaults to `5053`; override it with the `PORT` environment variable if needed.

## Free procurement index

The app searches a local SQLite/FTS index of free public OCDS data before using
the configured web engines. Build or refresh it with:

```bash
python procurement_ingest.py
```

The systemd service and timer in `deploy/` refresh the last 14 days of Find a
Tender data and the last two completed Sell2Wales calendar months each day.
The SQLite database is stored at `instance/procurement.sqlite3` and is retained
between application deployments.

## Notes

- Search conversations remain private in browser local storage.
- **Save chat .md** exports the complete conversation, attachments and source links.
- Uploads support PDF, DOCX, XLSX, CSV, TXT, Markdown, EML and MSG.
- Runtime settings are written to the ignored `settings.json` file.
- The underlying research engine remains aligned with `zageabb/general-search`; pricing-specific behaviour is primarily defined through this fork's default prompts and settings.
- Public PDFs can be read directly, which is particularly useful for tender documents, schedules of rates and procurement awards.
- The application validates public web destinations and redirects to reduce SSRF risk; Ollama may still be configured on a private network address.
