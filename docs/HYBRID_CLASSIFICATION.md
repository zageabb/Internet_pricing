# Hybrid Semantic Classification

Internet Pricing uses a semantic-first, code-governed classification architecture.

## Design principle

The LLM decides **what the request means**. Deterministic code decides **what that category is allowed to do**.

This avoids two failure modes:

1. endlessly expanding hard-coded keyword/regex lists to understand every product-family abbreviation;
2. allowing an LLM to invent categories, bypass commercial-evidence rules, or decide that research is complete without satisfying configured safeguards.

## Runtime flow

```text
User request
   |
   v
LLM semantic category proposal
(category + confidence + reason)
   |
   v
Code validation
- category exists
- category is enabled
- confidence >= threshold
   |
   +---- invalid / low confidence / model unavailable ----+
   |                                                       |
   v                                                       v
Accept semantic category                         Deterministic fallback classifier
   |                                                       |
   +---------------------------+---------------------------+
                               |
                               v
                    Lock category for this job
                               |
                               v
                    Resolve inherited search profile
                               |
                               v
              Search / evidence / stopping policy in code
```

The default confidence threshold is `0.70`. It can be changed with:

```bash
INTERNET_PRICING_CLASSIFIER_MIN_CONFIDENCE=0.70
```

The value is clamped to `0.50..0.95`.

## What the LLM can decide

The classifier receives the current enabled category catalogue. For each category it sees the category ID, display name, inherited search profile, category strategy, and a small set of configured phrases/keywords as examples or hints.

It is instructed to classify semantically rather than require literal keyword matches.

Examples where this helps:

- `400/275/33kV 1000MVA auto TX with OLTC` can be understood as `power-transformers` even if the deterministic fallback does not have every abbreviation.
- a future category can be recognised from its name and purpose without requiring a large vocabulary of aliases before it becomes useful.
- ambiguous product wording can be interpreted using the whole request rather than first-token matching.

The LLM returns only a proposal:

```json
{
  "category": "power-transformers",
  "confidence": 0.94,
  "reason": "The request describes a large autotransformer by voltage ratio, MVA and OLTC."
}
```

## What code still controls

A model proposal is accepted only when the proposed category exists in the saved category registry, is enabled, and meets the confidence threshold.

The model cannot:

- invent a new runtime category;
- select a disabled category;
- change category priority or configuration;
- change the inherited search profile;
- reduce the minimum number of qualifying priced sources;
- make FX or technical-only evidence count as commercial price evidence;
- bypass Power Transformer / HV scope checks;
- treat a complete EPC/substation value as an equipment price where specialist rules reject it;
- bypass independent-domain requirements;
- bypass deterministic stopping guards;
- make model knowledge outrank web-backed headline pricing.

Those remain deterministic application policy.

## Deterministic fallback

`classification_policy.py` still contains keywords, phrases and regex rules. They now serve two purposes:

1. a reliable fallback when the configured LLM is unavailable or returns invalid/low-confidence output;
2. an independent baseline shown in classification diagnostics.

They should no longer be treated as the only way the application can understand a product family. This means future category development should avoid adding every possible synonym merely to make classification function.

## Per-job classification lock

The selected category is stored in thread-local job context before the research runtime is chosen. All child searches in that job inherit the same category.

For example, once the root request is classified as `power-transformers`, a generated child query such as `TenderKart 1000MVA transformer award price` does not get independently reclassified as `general-product` or `hv-equipment` and change the research policy mid-run.

The context is cleared when the job finishes.

## Classification page

`/classifications` contains two useful views of classification:

- the live **Test a classification** control uses the hybrid semantic classifier and shows the selected category, confidence, threshold, search profile, and deterministic cross-check;
- `POST /api/classifications/test` remains the deterministic-only diagnostic endpoint for testing the fallback rules.

The live endpoint used by the page is:

```text
POST /api/classifications/test-hybrid
```

## Search lifecycle

Hybrid classification runs before the category-profile router. This is important: a semantic decision such as `power-transformers` is available before the application decides whether to run the HV, Consumer, Industrial, Service or General research mechanics.

After classification, the existing deterministic controls still apply:

```text
Semantic category
    -> configured search profile
    -> category-specific search strategy
    -> relevance gate
    -> evidence ranking
    -> page retrieval
    -> source interpretation
    -> commercial qualification
    -> minimum-source stopping rule
    -> answer synthesis
```

The LLM may still help interpret ambiguous sources and produce the final explanation, but the commercial stopping rule is not delegated to it.

## Future guidance

When a new category is added, focus first on:

- a clear display name;
- a useful category strategy/purpose;
- the correct inherited search profile;
- evidence and stopping requirements.

Add deterministic phrases/keywords for high-value obvious cases and fallback reliability, but do not attempt to encode the entire language of the product family in regex.

This preserves the intended division:

**LLM = semantic understanding and interpretation.**

**Code = policy, validation, safeguards and repeatability.**
