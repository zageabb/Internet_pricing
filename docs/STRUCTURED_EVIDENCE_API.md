# Structured evidence API

Completed Internet Pricing jobs now expose the retained research evidence used to synthesise the final answer.

`GET /api/search/<job_id>` keeps the existing `message`, `sources` and `events` fields and additionally returns, on completed researched pricing jobs:

- `job.retained_evidence`: bounded retained source records containing title, URL, originating query, relevant passages, extracted claims, focused source text, publication/obtained dates and content type.
- `job.pricing_evidence`: pricing classification metadata including category, whether the request is pricing-related, whether the retained set satisfied Internet Pricing's commercial-benchmark policy, and retained market-source count.

Reference FX evidence is included in `retained_evidence` with `kind: currency_reference`; ordinary retained commercial sources use `kind: market_source`.

This payload is intended for downstream applications such as Should-Cost Intelligence. It avoids reparsing final Markdown and allows downstream typed extraction, currency normalisation, scoring and audit persistence to operate on the same retained evidence that Internet Pricing used.

The existing browser/UI contract remains backward compatible; clients that do not use these fields are unaffected.
