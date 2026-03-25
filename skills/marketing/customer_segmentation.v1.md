---
id: customer_segmentation_v1
name: Customer Segmentation
version: "1.0"
domain: marketing
scope: strategy_readout
triggers:
  - persona
  - segment
  - audience
  - icp
  - messaging
  - keyword research
agent_role: worker
allowed_tools:
  - marketing.get_audience_insights
  - marketing.get_search_keywords
  - marketing.get_analytics_summary
inputs:
  - task_packet: "Bounded plan including product, market, objective, geography, and any existing customer knowledge"
  - existing_metrics: "Optional acquisition, retention, conversion, or content-performance data"
outputs:
  - segment_map: "Prioritized audience segments with pains, jobs-to-be-done, and buying triggers"
  - persona_cards: "Practical persona summaries with objections, language, and channels"
  - keyword_clusters: "Keyword opportunities grouped by segment and intent"
  - messaging_matrix: "Segment-specific value propositions, proof points, and CTA suggestions"
definition_of_done:
  - Segments are prioritized rather than presented as an undifferentiated list
  - Each segment includes pains, motivations, and likely objections
  - Keyword clusters are tied to segments and intent
  - Messaging recommendations differ by segment in a meaningful way
failure_modes:
  - generic_personas: "Personas are broad stereotypes with no usable distinctions"
  - segment_overlap: "Segments duplicate each other and create unclear targeting"
  - untethered_keywords: "Keyword recommendations are not mapped to segment needs"
  - channel_mismatch: "Suggested channels do not fit the identified audience behavior"
validators:
  - type: prioritization_check
    description: "Segments are ranked by opportunity, fit, or urgency"
  - type: differentiation_check
    description: "Each segment has distinct pains, proofs, and messaging"
  - type: keyword_mapping
    description: "Keyword clusters are attached to specific segments and intents"
estimated_tokens: 11000
---

# Customer Segmentation

## When to Use

Use this skill when the task is to turn a broad market or customer base into concrete, actionable audience segments that can guide copy, campaigns, and channel selection.

Typical uses:

- ICP definition for a new product
- Messaging refinement for an existing offer
- Audience mapping before paid or organic campaigns
- Search-intent mapping by persona

## Procedure

### 1. Gather Available Evidence

Start from what already exists:

- Known customer types from the task packet
- Product value proposition and constraints
- Existing conversion or retention patterns

Then enrich with data:

```
marketing.get_audience_insights(platform, segment)
marketing.get_search_keywords(property_id, date_range, filters)
marketing.get_analytics_summary(platform, property_id, date_range, dimensions)
```

### 2. Draft Candidate Segments

Build candidate segments around meaningful differences such as:

- Job-to-be-done
- Company size or maturity
- Role in the buying process
- Urgency and pain severity
- Budget sensitivity

Avoid demographic filler unless it changes message strategy.

### 3. Prioritize the Segments

Rank segments using the evidence available:

- Commercial fit
- Ease of reach
- Search demand or content pull
- Conversion likelihood
- Strategic importance

If evidence is thin, mark the ranking as provisional instead of overstating confidence.

### 4. Produce Persona Cards

For each priority segment, include:

- Core job or problem
- Desired outcome
- Key objections
- Proof they need before acting
- High-signal phrases they are likely to respond to
- Best-fit channels or content formats

Keep personas operational. They should help write or target better campaigns immediately.

### 5. Map Keywords and Messaging

Attach search and messaging guidance to each segment:

- Keyword clusters by intent
- Primary value proposition
- Proof points and examples
- CTA style
- Content or campaign ideas that fit the segment

### 6. Return the Strategy Readout

Summarize where to start:

- Primary target
- Secondary target
- Message differences worth testing first
- Data gaps that should be resolved with future campaigns or analytics

## Validation Checklist

- [ ] Segments are concrete and non-overlapping
- [ ] Priority order is explicit
- [ ] Persona cards are operational, not generic
- [ ] Keywords are tied to segments and intent
- [ ] Messaging matrix reflects real differences between segments
