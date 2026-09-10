# Classification & Rules

Internet Pricing has an editable category policy page at `/classifications`. The page is intentionally organised around each pricing category so category-specific behaviour can grow without becoming a single global rules file.

## Category-first structure

Each category has separate sections for:

1. **Classification** — active keywords, phrases and regular-expression patterns used to select the category.
2. **Search strategy** — active category-specific research guidance supplied to the pricing pipeline.
3. **Evidence requirements** — active minimum qualifying priced-source threshold and independent-domain requirement, plus editable evidence notes.
4. **Stopping rules** — the numerical threshold is active; the notes document intended category-specific stopping behaviour and provide space for richer rules later.
5. **Fallback & enrichment** — documents how model knowledge should be used relative to web pricing.
6. **Category extensions / notes** — an intentionally separate future area for new category-specific logic such as model aliases, rating tolerances, stock rules, regional normalization or source weighting.

Fields are labelled **Active**, **Reference**, **Threshold active · notes reference**, or **Future** in the UI so an editable documentation field is not confused with a rule that currently changes runtime behaviour.

## Current categories and defaults

| Category | Default qualifying priced sources | Independent domains | Purpose |
| --- | ---: | --- | --- |
| `hv-equipment` | 2 | Yes | HV/MV switchgear, transformers, disconnectors and related grid equipment |
| `service-project` | 2 | Yes | Installation, commissioning, maintenance, consultancy, construction and labour/project pricing |
| `consumer-retail` | 3 | Yes | Laptops, computers, phones, retail products and recognised retail product families |
| `industrial` | 2 | Yes | Industrial machines/components such as motors, pumps, compressors, drives and UPS/battery equipment |
| `general-product` | 3 | Yes | Catch-all when no specialist category matches |

`consumer-retail` includes product-family terms such as ThinkPad, ThinkBook, MacBook, Latitude, EliteBook, ZenBook, IdeaPad and Surface. For example, a bare `Lenovo ThinkPad X1 Carbon ... price` request should classify as `consumer-retail` even when the word `laptop` is omitted.

## Commercial stopping rule

A retained source is not automatically a commercial hit. The stop threshold counts qualifying **price-bearing** sources, not all retained evidence. Technical pages and currency-conversion sources therefore do not increase the priced-source count.

When `require_independent_domains` is enabled, several pages from the same website count as one source for stopping purposes. The default consumer policy therefore requires three independent matching priced listings before research may be described as having a sufficient market benchmark.

The threshold is deterministic. If the LLM coverage reviewer says the research is complete while the category still has fewer qualifying priced sources than configured, `classification_coverage.py` forces the research state back to incomplete and generates additional category-appropriate price searches.

## HV protection

The editable HV source threshold sits **on top of** the specialist HV benchmark validator. It does not replace the existing rating/scope checks. A whole-project contract value containing switchgear, transformers, cables and civil works is still rejected as a qualifying switchgear benchmark unless suitable line-item/commercial scope evidence exists.

This design is important: the page can adjust *how many* qualifying HV price sources are required without weakening the rules that determine whether a source is a valid HV price benchmark in the first place.

## Live classification test

The top of `/classifications` contains a **Test a classification** box. It calls the same saved classifier used by new searches and returns:

- selected category and label;
- exact reason the category matched;
- category priority;
- current minimum priced-source threshold;
- whether independent domains are required;
- current search strategy.

Use this before changing classification terms, especially when introducing a new product family or broad keyword.

## Saving and deployment

Edits are stored in `classification_rules.json` beside the application. The file is git-ignored, like `settings.json`, so local operational changes survive normal source updates without being committed back to the repository.

`Reset defaults` removes the local override and returns the application to the built-in defaults in `classification_policy.py`.

The current API endpoints are:

- `GET /classifications` — category-first admin page;
- `POST /api/classifications` — save all category rules;
- `POST /api/classifications/reset` — restore built-in defaults;
- `POST /api/classifications/test` — classify a supplied query using the currently saved policy.

## Future extension guidance

When category behaviour grows, prefer adding fields/logic inside that category's existing sections instead of adding another global switch. Useful future examples include:

- consumer: product-family aliases, generation matching, minimum specification similarity, stock-state requirements, marketplace policy;
- HV: voltage-class mappings, rating tolerances, AIS/GIS rules, equipment-family aliases, source weights;
- industrial: capacity/rating parsers, configuration similarity, OEM/distributor weighting;
- services: geography, labour class, mobilisation, travel and installed-scope normalization;
- general product: identify recurring families that deserve a new dedicated category rather than overloading the catch-all.

The design goal is for the page to become the visible policy map for Internet Pricing: classification, search, evidence, stopping and fallback should be inspectable by category before they are hidden in code.
