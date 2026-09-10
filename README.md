# Internet Pricing

Internet Pricing is a pricing-focused fork of [General Search](https://github.com/zageabb/general-search). It keeps the same conversation-first interface, live research activity, cited Markdown answers, browser-local chat history, document uploads, settings, and Markdown export while specialising the research workflow for market pricing and budget estimates.

The application is intended for difficult-to-price equipment and project packages where a simple retail search is not enough. It can search public procurement documents, schedules of rates, tender awards, purchase-order benchmarks, OEM technical pages, distributor listings and other relevant public evidence, then compare specification and scope before producing a cited budgetary estimate.

The pricing core works across product types. It selects a deterministic strategy for consumer/retail products, industrial products, HV equipment, services/projects, or a general product, while retaining the same evidence, date, currency-conversion and model-knowledge fallback rules. Because this is a pricing application, a bare recognised product description such as `Lenovo V15 16GB 512GB laptop` is treated as a request to find its price.

Internet Pricing uses `research-core` v0.2.x for shared evidence mechanics. The shared package preserves numeric/commercial evidence passages and provides generic evidence-aware ranking behaviour; Internet Pricing keeps pricing-specific query strategy, scope rules and stopping policy locally.

## Pricing behaviour

For pricing requests the assistant is instructed to:

- Treat price questions as web-research questions by default.
- Search using the exact equipment/specification plus complementary benchmark searches such as procurement, tender, award, schedule-of-rates and OEM queries.
- For complex HV equipment, split the request into evidence layers rather than requiring every rating, quantity and configuration detail in every search. Typical layers include feeder-panel awards, incomer transaction data, busbar/platform validation and source-focused commercial searches.
- Preserve planner-generated complementary searches when they share meaningful subject/rating context; they no longer need to repeat every original anchor.
- Prefer primary and authoritative commercial evidence over SEO pages or generic price aggregators.
- Treat price evidence and specification evidence as separate roles when necessary. A transaction/award can establish price while an OEM page establishes technical comparability.
- Capture the specification, quantity, scope boundary, source date and currency of each useful benchmark.
- Separate equipment-only supply from erection, testing, commissioning, civils, protection/control, cabling and complete installed-package costs where relevant.
- Do not treat a whole-project value as a sufficient HV equipment benchmark merely because the project contains the requested switchgear.
- Compare like-for-like scope before using a benchmark and explain important differences.
- Give low/base/high or reasonable tender ranges when the evidence supports estimation rather than a single false-precision figure.
- If searches return no readable evidence, fall back to model knowledge instead of returning nothing. Any pricing from that fallback is explicitly labelled indicative, not web-verified, and low confidence.
- Clearly label estimates and assumptions and keep externally verifiable price claims tied to citations.
- Preserve the General Search answer presentation: concise Markdown, tables where useful, inline source references and a source list.

Category strategies are deliberately separate:

- Consumer products prioritise exact model/specification retailer listings.
- Industrial products prioritise manufacturer and distributor catalogues, quotations and procurement evidence.
- HV equipment prioritises utility tenders, awards, frameworks, transaction data and schedules while comparing ratings and scope.
- Services and projects prioritise labour/day rates, schedules of rates, awards, geography and inclusions.
- Other products begin with exact-description supplier, distributor and catalogue searches.

A request such as `Find pricing for 11 kV AIS 3200 A switchboard, 25 kA, 2 incomers 2000 A and 8 feeders 630 A` is deliberately decomposed into searches such as feeder-panel award/BOQ evidence, 2000 A incomer import/export transactions, 3200 A busbar technical validation, and high-yield tender/transaction sources. The final answer can then combine those evidence records into a normalized estimate rather than pretending an exact ten-panel public quotation must exist.

## Web page reading

Internet Pricing keeps the lightweight reader as the default path. Public HTML and PDFs are fetched with bounded HTTP requests first, then structured commerce data, product metadata, tables and visible text are extracted.

For JavaScript-heavy commercial pages, an optional Playwright fallback uses headless Chromium only when a shortlisted page still lacks useful rendered commercial content after the lightweight fetch. The fallback:

- reuses one Chromium process and opens a fresh isolated browser context for each page;
- executes JavaScript and extracts the rendered DOM through the same structured/visible-text parser;
- renders at most three candidate pages per fetch batch by default;
- uses a 15 second navigation timeout by default;
- blocks images, video/media, fonts and common advertising/analytics hosts;
- validates browser requests as public URLs to retain the application's SSRF protections;
- caches successful rendered content through the existing retrieval cache;
- does not pass `--no-sandbox`, so Chromium retains its normal sandbox when the service runs as an unprivileged account;
- does not attempt to bypass logins, CAPTCHAs, bot challenges or other access controls.

Consumer/industrial/general-product pages can use the normal browser fallback. HV pages remain lightweight-first, but highly ranked tender/award/BOQ/transaction candidates—including known commercial evidence sources such as TenderKart, Volza and Zauba—may now use bounded Chromium rendering when the lightweight HTML omits the value. Service/project procurement pages remain on the lighter HTML/PDF path by default.

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
- Evidence ledgers identify `PRICE_EVIDENCE`, `SPEC_EVIDENCE`, `SUPPLIER_EVIDENCE` or `BACKGROUND_EVIDENCE` so the synthesis stage can understand why each retained source matters.
- Public PDFs can be read directly, which is particularly useful for tender documents, schedules of rates and procurement awards.
- The application validates public web destinations and redirects to reduce SSRF risk; Ollama may still be configured on a private network address.
