# Internet Pricing

Internet Pricing is a pricing-focused fork of [General Search](https://github.com/zageabb/general-search). It keeps the same conversation-first interface, live research activity, cited Markdown answers, browser-local chat history, document uploads, settings, and Markdown export while specialising the research workflow for market pricing and budget estimates.

The application is intended for difficult-to-price equipment and project packages where a simple retail search is not enough. It can search public procurement documents, schedules of rates, tender awards, purchase-order benchmarks, OEM technical pages, distributor listings and other relevant public evidence, then compare specification and scope before producing a cited budgetary estimate.

## Pricing behaviour

For pricing requests the assistant is instructed to:

- Treat price questions as web-research questions by default.
- Search using the exact equipment/specification plus complementary benchmark searches such as procurement, tender, award, schedule-of-rates and OEM queries.
- Prefer primary and authoritative commercial evidence over SEO pages or generic price aggregators.
- Capture the specification, quantity, scope boundary, source date and currency of each useful benchmark.
- Separate equipment-only supply from erection, testing, commissioning, civils, protection/control, cabling and complete installed-package costs where relevant.
- Compare like-for-like scope before using a benchmark and explain important differences.
- Give low/base/high or reasonable tender ranges when the evidence supports estimation rather than a single false-precision figure.
- Clearly label estimates and assumptions and keep externally verifiable price claims tied to citations.
- Preserve the General Search answer presentation: concise Markdown, tables where useful, inline source references and a source list.

A request such as `Find a price for 400 kV GIS switchgear, 2 incomers 2000 A and 6 feeders 630 A` should therefore trigger searches for current 400/420 kV GIS quotations or procurement benchmarks, comparable bay configurations and OEM technical context, then return a structured budget estimate with source-backed reasoning.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp settings.example.json settings.json
.venv/bin/python app.py
```

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
