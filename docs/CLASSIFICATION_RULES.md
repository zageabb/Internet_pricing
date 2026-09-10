# Classification & Rules

Internet Pricing has an editable category policy page at `/classifications`. The page is intentionally organised around each pricing category so category-specific behaviour can grow without becoming a single global rules file.

## Dynamic category management

Categories are now data-driven rather than fixed to a Python list. From `/classifications` you can:

- **Add category** — create a new category from a clean default.
- **Duplicate** — copy an existing category as the starting point for a more specialised category.
- **Rename** — edit the display name and category ID.
- **Reorder** — use **Up** and **Down**; classification evaluates enabled categories from top to bottom and the first match wins.
- **Enable / disable** — keep a category and its settings without allowing it to classify new searches.
- **Delete** — remove a category when the rules are saved.

`general-product` is a protected catch-all. It cannot be disabled or deleted and is always evaluated last.

Each category also has a **Search profile**. The category ID and its user-facing rules can be unique while the search profile inherits proven mechanics from one of:

- `general-product`
- `consumer-retail`
- `industrial`
- `service-project`
- `hv-equipment`

This lets a new category such as `power-transformers` reuse the strict HV relevance, search-engine fallback and evidence handling while still keeping transformer-specific classification, search strategy and stopping rules.

## Category-first structure

Each category has separate sections for:

1. **Category identity & classification** — ID, display name, enabled state, inherited search profile, keywords, phrases and regular-expression patterns.
2. **Search strategy** — active category-specific research guidance supplied to the pricing pipeline.
3. **Evidence requirements** — active minimum qualifying priced-source threshold and independent-domain requirement, plus editable evidence notes.
4. **Stopping rules** — the numerical threshold is active; the notes document intended category-specific stopping behaviour and provide space for richer rules later.
5. **Fallback & enrichment** — documents how model knowledge should be used relative to web pricing.
6. **Category extensions / notes** — an intentionally separate future area for new category-specific logic such as model aliases, rating tolerances, stock rules, regional normalization or source weighting.

Fields are labelled **Active**, **Reference**, **Threshold active · notes reference**, or **Future** in the UI so an editable documentation field is not confused with a rule that currently changes runtime behaviour.

## Current categories and defaults

| Category | Search profile | Default qualifying priced sources | Independent domains | Purpose |
| --- | --- | ---: | --- | --- |
| `power-transformers` | `hv-equipment` | 2 | Yes | Large/grid power transformers, GSU and autotransformers with transformer-specific commercial and technical comparison |
| `hv-equipment` | `hv-equipment` | 2 | Yes | HV/MV switchgear, disconnectors and other related grid equipment |
| `service-project` | `service-project` | 2 | Yes | Installation, commissioning, maintenance, consultancy, construction and labour/project pricing |
| `consumer-retail` | `consumer-retail` | 3 | Yes | Laptops, computers, phones, retail products and recognised retail product families |
| `industrial` | `industrial` | 2 | Yes | Industrial machines/components such as motors, pumps, compressors, drives and UPS/battery equipment |
| `general-product` | `general-product` | 3 | Yes | Protected catch-all when no specialist category matches |

`consumer-retail` includes product-family terms such as ThinkPad, ThinkBook, MacBook, Latitude, EliteBook, ZenBook, IdeaPad and Surface. For example, a bare `Lenovo ThinkPad X1 Carbon ... price` request should classify as `consumer-retail` even when the word `laptop` is omitted.

## Power Transformers

`power-transformers` is evaluated before the broad `hv-equipment` category so transformer-specific requests are not swallowed by the generic HV rule.

Typical matches include:

- `132/33kV 90MVA power transformer`
- `275/132kV 240MVA transformer ONAN/ONAF`
- `generator step-up transformer`
- `GSU transformer`
- `autotransformer`

The default transformer search strategy prioritises tender awards, BOQs, purchase orders, framework/contract values, OEM technical information and import/export transactions. Searches are deliberately transformer-specific and use ratings such as MVA and voltage ratio rather than reusing switchgear queries.

The evidence policy keeps transformer-level or line-item prices separate from complete substation/EPC project totals. Technical evidence can validate comparability but does not count toward the commercial stopping threshold. The default stopping rule requires two independent qualifying priced transformer benchmarks.

The transformer category already reserves future structured comparison space for:

- MVA rating;
- HV/LV/tertiary voltage ratios;
- vector group;
- impedance;
- cooling class such as ONAN/ONAF/ODAF;
- OLTC range and steps;
- no-load and load losses;
- insulation/BIL;
- noise;
- oil type;
- transport mass;
- bushings, radiators, fans/pumps and marshalling kiosk;
- protection/control and accessories;
- spares, installation, testing and commissioning.

## Commercial stopping rule

A retained source is not automatically a commercial hit. The stop threshold counts qualifying **price-bearing** sources, not all retained evidence. Technical pages and currency-conversion sources therefore do not increase the priced-source count.

When `require_independent_domains` is enabled, several pages from the same website count as one source for stopping purposes. The default consumer policy therefore requires three independent matching priced listings before research may be described as having a sufficient market benchmark.

The threshold is deterministic. If the LLM coverage reviewer says the research is complete while the category still has fewer qualifying priced sources than configured, `classification_coverage.py` forces the research state back to incomplete and generates additional category-appropriate price searches.

## Specialist profile protection

The editable source threshold sits **on top of** the specialist benchmark validator. It does not replace rating/scope checks. Categories that inherit the `hv-equipment` search profile also inherit the strict HV relevance and retrieval pipeline.

For switchgear, a whole-project contract value containing transformers, cables and civil works is not automatically a valid switchgear benchmark. For Power Transformers, a complete substation/EPC value does not qualify unless a transformer line item or suitably scoped transformer value can be identified.

This design is important: the page can adjust *how many* qualifying price sources are required without weakening the rules that determine whether a source is a valid specialist benchmark in the first place.

## Live classification test

The top of `/classifications` contains a **Test a classification** box. It calls the same saved classifier used by new searches and returns:

- selected category and label;
- exact reason the category matched;
- category priority;
- inherited search profile;
- current minimum priced-source threshold;
- whether independent domains are required;
- current search strategy.

Use this before changing classification terms, especially when introducing a new product family or broad keyword.

## Adding a new category

A safe workflow is:

1. Find the closest existing category and click **Duplicate**, or click **Add category** for a clean category.
2. Give it a unique category ID and display name.
3. Select the closest inherited Search profile.
4. Add narrow phrases/keywords/patterns and move the category above any broader category that could match first.
5. Set its priced-source threshold and evidence requirements.
6. Use **Test a classification** on several positive and negative examples.
7. Save the rules and run a real research request.

Prefer narrow phrases and distinctive terms to a very broad single keyword. For example, `power transformer` is safer than making every occurrence of `transformer` automatically mean the specialised Power Transformers category.

## Saving and deployment

Edits are stored in `classification_rules.json` beside the application. The file is git-ignored, like `settings.json`, so local operational changes survive normal source updates without being committed back to the repository.

The rules format is currently version 3. Existing version 1/2 installations are migrated automatically. Version 3 introduced the `power-transformers` default and dynamic category metadata such as `enabled`, `order` and `search_profile`. Once an installation has saved version 3, a category that the user deliberately deletes is not silently recreated on future starts.

`Reset defaults` removes the local override and returns the application to the built-in defaults in `classification_policy.py`, including Power Transformers.

The current API endpoints are:

- `GET /classifications` — category-first admin page;
- `POST /api/classifications` — save all categories and rules;
- `POST /api/classifications/reset` — restore built-in defaults;
- `POST /api/classifications/test` — classify a supplied query using the currently saved policy.

## Future extension guidance

When category behaviour grows, prefer adding fields/logic inside that category's existing sections instead of adding another global switch. Useful future examples include:

- consumer: product-family aliases, generation matching, minimum specification similarity, stock-state requirements, marketplace policy;
- power transformers: rating/voltage normalization, cooling and OLTC matching, loss capitalization, transport/accessory scope and transformer-specific source weights;
- HV: voltage-class mappings, rating tolerances, AIS/GIS rules, equipment-family aliases, source weights;
- industrial: capacity/rating parsers, configuration similarity, OEM/distributor weighting;
- services: geography, labour class, mobilisation, travel and installed-scope normalization;
- general product: identify recurring families that deserve a new dedicated category rather than overloading the catch-all.

The design goal is for the page to become the visible policy map for Internet Pricing: classification, search, evidence, stopping and fallback should be inspectable by category before they are hidden in code.
