# Pricing Recovery and Model-Knowledge Fallback Policy

This document records the pricing policy introduced after the September 2026 11 kV AIS regression test. It complements `RESEARCH_SEARCH_LESSONS.md` and `HV_RELEVANCE_PIPELINE.md`.

## Reference failure

The reference request was:

```text
11kV AIS 3000A switchboard, 25kA,
2 incomers 2000A,
8 x feeders 630A
```

After the relevance fixes, Internet Pricing successfully found genuine web evidence, but the retained sources were mainly technical specifications. The final answer therefore confirmed the equipment ratings but returned no useful price, despite public tender/transaction benchmarks being discoverable with more price-focused searches.

The saved result also added an exchange-rate source even though no monetary evidence had been retained. That made the source list look more commercial than the actual evidence set.

## Policy hierarchy

For HV pricing requests the application should now use this order:

```text
1. Web-backed exact/comparable price evidence
2. Web-backed component price evidence + technical comparability
3. Additional deterministic price-recovery searches
4. Web-backed main price + model-knowledge accessory/package breakdown
5. Model-knowledge headline price only as the final fallback
```

The important principle is:

> Model knowledge must not compete with web evidence for the main equipment price. It may supplement a web-backed price with clearly labelled budgeting allowances, and it may provide the headline budget only after web price recovery is exhausted.

## Price-recovery searches

When retained HV evidence does not contain a sufficiently comparable commercial benchmark, follow-up search slots are reserved for deterministic commercial searches rather than allowing technical LLM follow-ups to consume the whole list.

For the reference case the recovery pattern includes searches similar to:

```text
TenderKart "11kV" "630A" "25kA" VCB panel award price
Volza "11kV" "2000A" "25kA" switchgear transaction value
"11kV" "630A" VCB panel BOQ winning bid unit price
"11kV" "2000A" incomer switchgear import export customs price
Zauba "11kV" switchgear import price transaction
"11kV" "25kA" switchgear quotation commercial offer price
```

The original user specification remains the technical comparison target. Relaxing the search wording must not silently relax the requested equipment.

## Deterministic retention of obvious price evidence

A clearly price-bearing HV tender, BOQ, quotation, import/export or transaction result should not depend entirely on the LLM source-review step.

The application may deterministically retain a source when all of the following are true:

- it passes the HV equipment-relevance gate;
- it contains a visible monetary value;
- it has line-item/commercial context such as unit price, BOQ, winning bid, quotation, transaction, shipment, customs, import or export; or it is from a known transaction evidence source;
- it is not merely a mixed whole-project total containing multiple unrelated scopes without a separable switchgear line item.

This is an evidence-retention rule, not permission to treat every retained price as the final benchmark. The existing scope/comparability sufficiency check still decides whether the source can end the research or drive the headline estimate.

## FX behaviour

Do not add currency-conversion evidence when the retained source set contains no commercial monetary value.

Correct behaviour:

```text
technical evidence only -> no FX lookup/source
price evidence retained -> dated FX may be obtained when useful
```

An exchange-rate source must never be used to make a technical-only result appear to contain pricing evidence.

## Model-knowledge use

### When a web-backed main price exists

The web-backed main equipment price remains authoritative.

Model knowledge may add a separate section for budgeting allowances such as:

- protection and control;
- metering;
- engineering/design;
- spares;
- freight/packing;
- erection, testing and commissioning;
- contingency.

These should normally be expressed as percentage/range allowances relative to the web-backed equipment subtotal rather than as a second competing equipment price.

The section must be clearly labelled `NOT WEB-VERIFIED` and must not invent citations, current quotes or exchange rates.

### When web price recovery fails

A model-knowledge equipment price is the final fallback, not an early substitute for research.

The fallback should contain:

- a clearly labelled `NOT WEB-VERIFIED` heading;
- equipment-only low/base/high budget;
- a suggested estimating figure;
- low confidence;
- optional accessory/package allowances;
- no claim that the value is a current quote;
- no invented citations or FX rates.

Returning only “obtain an RFQ” is not sufficient for the Internet Pricing application when the user asked for a budget and the web search has been exhausted.

## Answer separation

A healthy output should make the boundary obvious:

```text
Web-backed benchmark
    -> cited price/source/date/scope

Derived equipment estimate
    -> arithmetic from cited inputs

Indicative package allowances — NOT WEB-VERIFIED
    -> model-knowledge percentage/range assumptions
```

If no web-backed price was found:

```text
Web findings
    -> technical/spec evidence and failed price-recovery explanation

Final fallback budget — NOT WEB-VERIFIED
    -> model-knowledge low/base/high equipment price and allowances
```

## Regression expectations

For future tests of the reference 11 kV AIS request, verify that:

1. technical evidence alone does not cause the research to stop;
2. price-recovery searches include TenderKart/Volza-style award and transaction intent;
3. obvious price-bearing line-item evidence can survive source review deterministically;
4. mixed whole-project totals are not promoted as equipment prices;
5. FX evidence is absent when no price evidence exists;
6. a web-backed main price is not replaced by a model-generated headline price;
7. model knowledge may still provide a clearly labelled accessory/package breakdown;
8. if all web price recovery fails, the final answer still gives a clearly labelled model-knowledge low/base/high budget rather than only recommending an RFQ.
