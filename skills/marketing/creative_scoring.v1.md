---
id: creative_scoring_v1
name: Creative Scoring
version: "1.0"
domain: marketing
scope: read_only
triggers:
  - score
  - creative review
  - ad review
  - hook review
  - cta review
  - preflight
agent_role: reviewer
allowed_tools:
  - marketing.get_audience_insights
  - marketing.check_brand_compliance
  - marketing.compare_campaigns
inputs:
  - asset_pack: "Draft ad copy, scripts, concepts, or creative variants to evaluate"
  - task_packet: "Original brief including objective, audience, offer, and target platform"
  - existing_metrics: "Optional historical performance data for comparison"
outputs:
  - scorecard: "Per-asset scoring across hook, clarity, relevance, proof, CTA, and brand fit"
  - flagged_issues: "Actionable weaknesses, policy risks, and likely failure points"
  - winner_shortlist: "Best candidates to test first with reasons"
  - test_recommendations: "Specific revision or experiment ideas"
definition_of_done:
  - Every provided asset is reviewed
  - Scores are tied to explicit criteria rather than intuition alone
  - Risks are flagged before launch
  - Recommendations identify what to test next, not only what is wrong
  - No creative is published or modified automatically
failure_modes:
  - vague_scoring: "Scores are not supported by observable reasons"
  - metric_blindness: "Historical data is ignored when it is available"
  - false_precision: "Scoring implies certainty that the evidence does not support"
  - review_drift: "Review focuses on personal taste instead of task objective"
validators:
  - type: coverage_check
    description: "Every asset in the pack receives a score and rationale"
  - type: criteria_check
    description: "Hook, clarity, relevance, proof, CTA, and brand fit are all reviewed"
  - type: actionability_check
    description: "Recommendations identify concrete next tests or edits"
estimated_tokens: 9000
---

# Creative Scoring

## When to Use

Use this skill as a read-only quality gate before budget is spent or creative is routed to production.

Typical uses:

- Reviewing ad copy variants before launch
- Ranking hooks for short-form video scripts
- Comparing several campaign concepts against the same brief
- Flagging weak CTA or message-audience mismatch

## Procedure

### 1. Normalize the Evaluation Context

Read the brief and record:

- Objective
- Audience segment
- Offer
- Platform or placement
- Non-negotiable claims or compliance constraints

If historical data is provided, note which benchmarks matter most: CTR, thumb-stop rate, CVR, CPA, or engagement quality.

### 2. Score Every Asset Against the Same Rubric

Review each asset on:

- Hook strength
- Clarity of the offer
- Audience relevance
- Credibility and proof
- CTA clarity
- Brand fit and policy risk

Use a simple numeric scale only if each score is backed by a short rationale.

### 3. Use Available Context, Not Taste

Where useful, pull audience context or compare against past results:

```
marketing.get_audience_insights(platform, segment)
marketing.compare_campaigns(campaign_ids, metrics, date_range)
marketing.check_brand_compliance(content, brand_guidelines)
```

Prefer evidence like "this variant buries the offer until line 4" over broad opinions like "this feels weak."

### 4. Flag the Failure Points

For each weak asset, identify the highest-leverage issue:

- Slow or generic opening
- Unclear offer
- Weak proof
- Mismatched CTA
- Off-brand or risky language

Do not produce a wall of notes. Focus on the issues most likely to affect performance or approval.

### 5. Return the Testing Recommendation

Rank the best candidates and recommend:

- Which assets should be tested first
- Which should be revised before testing
- Which should be discarded

Where possible, pair each recommendation with one concrete next experiment.

## Validation Checklist

- [ ] Every asset was reviewed
- [ ] Scores are linked to explicit criteria
- [ ] Brand and policy risks are flagged
- [ ] Winner shortlist is prioritized
- [ ] Test recommendations are concrete
- [ ] No launch action was taken
