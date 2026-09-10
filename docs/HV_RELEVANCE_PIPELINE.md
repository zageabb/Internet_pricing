# HV Relevance and Candidate Queue Fix

## Purpose

This note records the September 2026 follow-up regression discovered after the initial `research-core` v0.2.1 evidence improvements. The shared evidence changes were working, but an 11 kV AIS pricing request still fell back to model knowledge because irrelevant procurement results were being admitted and consuming the page-reading opportunity.

Reference request:

```text
11kV AIS 3000A switchboard, 25kA, 2 incomers 2000A, 8 x feeders 630A
```

## Root cause

The failure was not primarily web availability. Searches returned results, but the downstream pipeline treated weak or unrelated procurement results badly.

The important failure modes were:

1. The old non-consumer relevance filter returned all candidates again when zero candidates matched. This meant an unrelated tender could survive simply because nothing better matched.
2. Search-backend fallback counted an engine as successful when it returned any result, even when every result was irrelevant to the requested equipment.
3. URLs were marked `seen` when discovered rather than when actually attempted. A relevant result outside the small fetch shortlist could therefore disappear from later consideration.
4. The shared commercial-evidence score was capable of increasing the rank of a tender/award page after the weak relevance filter had admitted it. Commercial strength was being allowed to compensate for subject irrelevance.
5. The final fallback message said `Web unavailable; using model knowledge` even when web search had succeeded and the real failure was that no acceptable evidence was retained.

## Design invariant

The core rule introduced by this fix is:

> Commercial evidence quality may improve the rank of a relevant result; it must never make an irrelevant result relevant.

The processing order for HV research is therefore:

```text
Search
  -> equipment relevance gate
  -> subject/rating score
  -> shared commercial-evidence score
  -> persistent candidate queue
  -> fetch / browser / PDF
  -> passage extraction
  -> source review
  -> benchmark sufficiency
  -> synthesis
```

## Strict HV equipment relevance gate

HV results are now checked deterministically before commercial ranking is allowed to help them.

For a switchgear/switchboard request, a candidate must contain recognisable electrical equipment context such as:

- switchgear / switchboard;
- VCB / vacuum circuit breaker;
- metal-clad / medium-voltage switchgear;
- incomer panel / feeder panel / breaker panel;
- or a generic `panel` only when accompanied by electrical rating and breaker/feeder/incomer/busbar context.

Known wrong families such as surge arrester results are rejected when they were not requested. Results that are clearly below 1 kV are rejected when the target is an HV/MV request of 3 kV or above.

A 12 kV equipment class remains acceptable as a useful comparator for an 11 kV system. AIS/GIS differences reduce relevance rather than silently becoming an exact match.

If no candidates pass this gate, the result is an empty candidate set. The old `matched or candidates` fallback must not return.

## Search backend behaviour

For HV queries, search engines are now judged by relevant results rather than raw result count.

Status output is designed to show values such as:

```text
duckduckgo: 6 / 0 relevant
mojeek: 6 / 0 relevant
startpage: 6 / 2 relevant
yahoo: 6 / 1 relevant
```

The search can continue to another configured backend when the first engines return only unrelated material. It can stop once enough relevant coverage has been obtained.

This policy is deliberately HV-specific. Other categories retain their existing search behaviour unless a separate regression demonstrates the same need.

## Persistent candidate queue

The runtime now distinguishes these states:

- `discovered_urls` — returned by search or the procurement index;
- `relevant_urls` — passed the equipment gate;
- `attempted_urls` — actually scheduled for page retrieval;
- `readable_urls` — returned enough readable content to inspect;
- retained evidence — passed source review and entered the evidence ledger.

A URL is no longer considered attempted merely because a search engine returned it.

Relevant candidates remain in a persistent queue across research rounds. If the first batch is rejected or unreadable, lower-ranked relevant candidates remain available instead of being discarded before they are opened.

The configured page budget now reflects attempted pages for the HV runtime rather than the number of successfully retained sources.

## Progressive query relaxation

The complete requirement remains the target specification used for comparison, but later searches can become simpler when exact searches perform poorly.

Examples for the reference request include:

```text
"11kV" "630A" VCB feeder panel unit price
"11kV" "2000A" incomer switchgear price
"11kV" "25kA" switchgear tender BOQ price
12kV AIS switchgear "630A" price
11kV VCB panel tender award price
12kV medium voltage AIS switchgear BOQ unit price
11kV switchgear import export transaction value
11kV AIS switchgear quotation commercial offer
```

Relaxing the search does not relax the original engineering requirement. The source still has to be compared with the full requested specification before it can drive a benchmark.

LLM-generated follow-up searches are also filtered so an unrelated follow-up query cannot steer the HV search into another procurement subject.

## Diagnostics and fallback wording

Every HV research run now emits an aggregate research diagnostic similar to:

```text
47 search results -> 9 equipment-relevant -> 8 pages attempted -> 6 readable -> 2 retained
```

Rejection counts are also retained for known deterministic/review outcomes, including:

```text
WRONG_EQUIPMENT_FAMILY
WRONG_VOLTAGE_CLASS
INSUFFICIENT_ELECTRICAL_CONTEXT
SOURCE_REVIEW_REJECTED
SOURCE_REVIEW_FAILED
```

The fallback wording now distinguishes:

- no search results;
- search results but no equipment-relevant candidates;
- relevant candidates but no available page attempts;
- attempted pages that were unreadable;
- readable pages where no acceptable pricing evidence was retained.

`Web unavailable` must only be used when that is actually the failure. A successful search followed by evidence rejection should be reported as such.

## Regression tests

`tests/test_hv_relevance_runtime.py` covers the reference failure pattern. Tests include:

- an aquarium/procurement award with a large GBP value is rejected for an 11 kV switchboard request;
- zero relevant candidates returns an empty set rather than restoring unrelated pages;
- a 12 kV AIS switchgear result remains a valid comparator for an 11 kV system;
- commercial-evidence scoring cannot revive a rejected unrelated candidate;
- the search continues through configured engines when early engines return zero relevant results;
- relaxed searches preserve important component/rating intent without repeating the whole board configuration;
- multiple unattempted candidates remain in the queue;
- fallback wording distinguishes evidence rejection from a web outage.

## Deployment note

This change is application code, not a new `research-core` release. A server only needs the updated Internet Pricing repository code and a process restart/reload. The existing `research-core` v0.2.1 pin remains valid.

When validating a deployment, use the reference request and inspect the activity log. Healthy behaviour should include an `Applied equipment-relevance gate` event, backend statuses with relevant counts, and a final `Research diagnostics` funnel. Unrelated tenders such as aquarium/construction awards should not reach the page-reading stage merely because they contain a large contract value.
