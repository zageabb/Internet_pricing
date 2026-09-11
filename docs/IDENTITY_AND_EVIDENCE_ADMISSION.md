# Identity Preservation and Evidence Admission

This document records the safeguards added after regression testing with an unverified consumer product (`Pixel 11 Fold`) and a `150MVA` power-transformer request.

## Problem observed

Two separate runs demonstrated that correct classification alone is not enough:

1. A consumer request could be semantically classified correctly but the planning model could rewrite the requested identity into a related product. Search then used the rewritten identity, and a no-evidence fallback could invent launch dates, specifications and prices.
2. A power-transformer request could be classified correctly but generic procurement awards containing the word `transformer` and a monetary value could still enter the evidence ledger. The benchmark validator rejected them later, but the answer writer could still display them as apparent market evidence.

The design principle is now:

> Preserve the original requested identity/specification as an invariant. Validate a source against that invariant before a commercial value enters retained evidence.

## Original-request invariant

The hybrid classifier now stores the exact request that started the research job in thread-local job context. Downstream category policies may read this through `search.active_request_query()`.

The LLM may still rewrite the request for planning and reasoning, but that rewrite is not authoritative for:

- consumer product identity;
- specialist equipment ratings;
- commercial evidence admission;
- final fallback identity.

## Consumer identity policy

`request_identity_policy.py` applies to categories using the `consumer-retail` search profile.

### Search generation

Initial searches are built from the original requested identity rather than the planner rewrite. LLM-planned searches are retained only if they still contain the distinguishing identity tokens.

A request such as `Pixel 11 Fold price` therefore cannot silently become a search for `Google Pixel Fold price`.

### Candidate filtering

Search-result titles/snippets must retain the product identity. Numeric/alphanumeric model tokens such as `11`, `x1` or `13` are treated as critical identity tokens. This prevents a related generation/model from passing merely because the brand/family overlaps.

### Source admission

Before LLM source review, a consumer source is rejected with `PRODUCT_IDENTITY_MISMATCH` if the exact requested identity is not present strongly enough in the source material.

### Progressive follow-up

Later searches remove quotation/specification clutter while retaining the identity. For example:

- `"pixel 11 fold" price`
- `pixel 11 fold price`
- `pixel 11 fold retailer listing`
- `pixel 11 fold availability`
- `pixel 11 fold official product`

The search becomes broader without changing the product.

### Safe fallback

If the exact product does not reach the configured priced-source threshold, model knowledge is not allowed to invent a launch date, specification set or headline price. The answer is replaced with an explicit **Exact product price not verified** result.

This is intentionally different from specialist industrial/HV fallback, where a clearly labelled model-knowledge budget can still be useful after web-price recovery is exhausted.

## Power Transformer admission policy

Power-transformer sources are now validated before price-bearing evidence is retained.

### Equipment family

The source must actually describe a transformer/autotransformer.

### MVA comparison

If the request specifies MVA, the source must specify MVA too. The closest source rating must be within 50% of the requested rating to qualify as a commercial comparator.

A generic `transformer` award with no MVA is rejected as `MISSING_MVA_RATING`.

### Voltage comparison

If the request gives a voltage ratio, the first two voltage levels are identity-bearing. The source must contain comparable values within 15% of both requested levels.

This prevents a 33/11kV distribution transformer from qualifying for a 400/132kV power-transformer request.

### Quantity and scope

Complete substation/EPC values are rejected unless transformer unit/line-item scope is identifiable. Multi-unit totals are rejected unless a unit/per-transformer value is clear.

Important rejection reasons include:

- `WRONG_EQUIPMENT_FAMILY`
- `MISSING_MVA_RATING`
- `MVA_OUT_OF_RANGE`
- `MISSING_VOLTAGE_RATING`
- `VOLTAGE_MISMATCH`
- `PROJECT_TOTAL_NOT_TRANSFORMER_PRICE`
- `MULTI_UNIT_TOTAL_WITHOUT_UNIT_PRICE`
- `INSUFFICIENT_COMMERCIAL_SCOPE`
- `IMPLAUSIBLE_LPT_PRICE_SCOPE`

### Sanity floor

For large transformers (50MVA or above), an obviously tiny visible USD/EUR/GBP amount below 25,000 is rejected as likely wrong scope even if the surrounding text contains the requested ratings. This is a secondary safety check; rating and scope validation remain primary.

## Progressive transformer searches

Transformer follow-up searches no longer repeat the same tightly quoted `MVA + voltage ratio` string every round.

The sequence deliberately broadens:

1. exact MVA + voltage-ratio tender/BOQ/PO/transaction searches;
2. MVA-only or voltage-ratio-only commercial searches;
3. nearby MVA comparators while preserving the original target for validation;
4. broader large-power-transformer BOQ, purchase-order, import/export and quotation evidence.

Crucially, broadening the discovery query does **not** broaden the final acceptance rules. A 100MVA source may be discoverable for a 150MVA target, but it still has to pass the numeric comparator rules before its price is retained.

## Separation of diagnostics and evidence

A rejected procurement record may still be visible in search/activity diagnostics, but it must not be placed in the retained evidence ledger and must not appear in the opening price-comparison table.

This distinction is deliberate:

- **discovered result** — useful for diagnosing search behaviour;
- **read source** — page/snippet was inspected;
- **retained evidence** — passed equipment/identity/rating/scope rules;
- **qualifying priced benchmark** — retained evidence that also satisfies the category's commercial stopping policy.

Only the latter two belong in the final answer as evidence.
