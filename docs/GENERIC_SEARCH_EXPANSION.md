# Generic Search Expansion and Comparator Ladder

Internet Pricing now uses one generic expansion mechanism for every pricing category rather than adding product-specific aliases or comparator logic to each category.

## Goal

Exact search remains the first preference, but failure to find an exact result must not mean the research stops or repeatedly submits the same tightly constrained query.

The search progression is:

1. Exact requested identity/specification
2. Canonical-name / alias expansion
3. Near-spec comparator
4. Adjacent-family comparator
5. Broad family benchmark

The ladder is generated from the original user/document-derived request and the active category/search profile.

## LLM and code responsibilities

The expansion-planning LLM proposes concise search hypotheses for the four expansion levels. These proposals are not facts and do not establish equivalence.

Code remains responsible for:

- preserving the original request as the comparison target;
- tagging each expansion query with its ladder level and rationale;
- ensuring exact/category-specific searches are not dropped to make room for expansions;
- keeping comparator evidence out of the exact commercial stopping threshold;
- preserving the category's minimum-source and independent-domain requirements;
- passing expanded hits to source review even if an exact deterministic gate would reject their changed rating/model/specification;
- labelling expansion evidence in the evidence ledger supplied to final synthesis.

The source-review LLM decides whether an expanded hit is useful to the original request. It is explicitly told that the expansion is a search hypothesis, not proof of equivalence, and that it must identify material differences.

## Expansion levels

### Canonical-name / alias expansion

Used for likely official names, manufacturer naming, expanded acronyms, abbreviations or alternate word order.

Example:

`Pixel 11 Fold price`

may produce a hypothesis such as:

`Google Pixel 11 Pro Fold retailer price`

The search does not assert that those names are equivalent. An authoritative source may verify the relationship during source review.

### Near-spec comparator

Same family with a relatively small generation, capacity, rating, size, configuration or market variation.

Example for a 150 MVA transformer:

`160MVA 220/132kV power transformer award price`

### Adjacent-family comparator

Same underlying product/equipment family but with one material specification difference that may still be commercially informative.

### Broad family benchmark

A wider family-level benchmark used when exact and near comparators remain scarce.

Broad results are useful for context only and receive the largest ranking penalty.

## Evidence admission

Expanded search results are allowed through the early exact-identity/rating gates so that the source-review LLM can decide whether the hit is useful.

This does not weaken exact evidence safeguards for ordinary, non-expanded results.

For example, a 160 MVA transformer result may be retained as a comparator for a 150 MVA request even when its voltage ratio differs. The source-review LLM must explain the difference. A random unrelated tender remains subject to the normal deterministic relevance rules unless it came from an explicitly tagged expansion query, in which case it still has to pass LLM source review before retention.

## Stopping behaviour

Near-spec, adjacent and broad comparator prices do **not** count toward the exact commercial benchmark threshold.

This means the system can retain and discuss useful comparators while continuing to look for exact or canonical evidence.

Canonical-name evidence may still contribute if the downstream exact identity/evidence rules independently support it; the expansion label alone never makes it exact.

## Final answer behaviour

The evidence ledger records the expansion relation and includes the statement `equivalence not assumed`.

If exact benchmark requirements are not met but useful priced comparator evidence exists, final review is instructed to:

- use the comparator evidence where genuinely informative;
- distinguish exact, canonical, near, adjacent and broad evidence;
- state the important differences from the requested item;
- never claim the comparator price as the observed price of the requested item;
- avoid saying that no usable price exists merely because only comparator prices were retained.

Model-knowledge fallback remains separate from web-backed comparator evidence.

## Why this is generic

The same mechanism applies to consumer products, industrial equipment, services/projects, HV equipment, power transformers and future categories created on the Classifications page.

Category-specific search strategies and hard safeguards remain available underneath the generic ladder. The ladder only broadens discovery and supplies relation metadata; it does not replace category policy.
