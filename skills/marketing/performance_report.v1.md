---
id: performance_report_v1
name: Performance Report
version: "1.0"
domain: marketing
scope: analytics_read_only
triggers:
  - performance
  - report
  - attribution
  - fatigue
  - winner
  - analytics
agent_role: reviewer
allowed_tools:
  - marketing.get_campaign_metrics
  - marketing.get_analytics_summary
  - marketing.get_social_analytics
  - marketing.compare_campaigns
inputs:
  - task_packet: "Bounded request including platform, date range, objective, and campaigns or properties to analyze"
  - existing_metrics: "Optional baseline targets or prior reporting periods"
outputs:
  - executive_summary: "Concise performance readout with the main business signal first"
  - winner_loser_table: "Best and worst performers with evidence"
  - fatigue_flags: "Creatives or segments showing decay, saturation, or spend inefficiency"
  - attribution_notes: "What the data does and does not support"
  - next_tests: "Highest-priority follow-up experiments"
definition_of_done:
  - Reporting period and objective are explicit
  - Performance conclusions are tied to metrics and comparisons
  - Attribution caveats are stated where the data is ambiguous
  - Recommendations include concrete next tests
  - No campaign changes are made automatically
failure_modes:
  - vanity_metric_bias: "The report overweights impressions or clicks without relating them to the goal"
  - false_attribution: "The report claims causality that the available data does not support"
  - hidden_decay: "Creative fatigue or efficiency drift is missed"
  - unreadable_summary: "The key decision signal is buried in metric dumps"
validators:
  - type: period_check
    description: "Date range, goal, and comparison basis are explicit"
  - type: metric_alignment
    description: "Metrics used in the report match the stated objective"
  - type: decision_quality
    description: "Recommendations follow from the data and are specific enough to act on"
estimated_tokens: 10000
---

# Performance Report

## When to Use

Use this skill when the task is to analyze campaign or content performance and convert raw metrics into clear operating decisions.

Typical uses:

- Weekly ad-performance review
- Cross-campaign comparison
- Creative fatigue monitoring
- Basic attribution readout before planning the next test cycle

## Procedure

### 1. Lock the Reporting Frame

Start with the analysis frame:

- Platform or property
- Date range
- Objective metric: qualified traffic, leads, purchases, retention, etc.
- Comparison basis: previous period, control, or sibling campaigns

If the task lacks a goal metric, define one explicitly before interpreting the data.

### 2. Pull the Relevant Metrics

Use the narrowest tools that answer the question:

```
marketing.get_campaign_metrics(platform, campaign_id, date_range)
marketing.get_analytics_summary(platform, property_id, date_range, dimensions)
marketing.get_social_analytics(platform, account_id, date_range)
marketing.compare_campaigns(campaign_ids, metrics, date_range)
```

Ignore metrics that do not help with the stated objective.

### 3. Identify Winners, Losers, and Decay

Look for:

- Strong performers worth scaling or reusing
- Underperformers worth pausing or rewriting
- Signs of fatigue: falling CTR, rising CPA, lower engagement quality, frequency issues, or declining conversion efficiency

Distinguish between creative problems, audience problems, and tracking uncertainty.

### 4. State Attribution Carefully

Return what the data supports:

- Directly observed relationships
- Reasonable but uncertain inferences
- Known blind spots in the data

Do not claim precise attribution if the available metrics are directional only.

### 5. Recommend the Next Test Cycle

Turn the report into actions:

- What to scale
- What to refresh
- What to stop
- What to test next

Each recommendation should tie back to a metric pattern in the report.

## Validation Checklist

- [ ] Objective and date range are explicit
- [ ] Metrics match the reporting goal
- [ ] Winners and losers are evidence-backed
- [ ] Fatigue or efficiency drift is addressed
- [ ] Attribution caveats are stated
- [ ] Next tests are concrete and prioritized
