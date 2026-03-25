---
id: social_campaign_v1
name: Social Campaign
version: "1.0"
domain: marketing
scope: multi_asset_draft
triggers:
  - social
  - campaign
  - launch
  - post
  - ad copy
  - platform
agent_role: worker
allowed_tools:
  - marketing.get_audience_insights
  - marketing.get_competitor_content
  - marketing.check_brand_compliance
  - marketing.create_content_draft
  - marketing.create_draft_campaign
inputs:
  - task_packet: "Bounded plan including offer, audience, objective, target platforms, and mandatory constraints"
  - brand_guidelines: "Voice, claims, visual guardrails, banned phrases, and CTA rules"
  - existing_metrics: "Optional prior campaign data, winning hooks, and performance constraints"
outputs:
  - campaign_angle: "Core message, hook themes, proof points, and CTA strategy"
  - platform_variants: "Platform-formatted copy variants for each requested surface"
  - test_matrix: "Structured creative test ideas across hooks, offers, and CTAs"
  - compliance_report: "Brand and policy risks found before launch"
definition_of_done:
  - One core campaign angle is defined before variants are produced
  - Copy is adapted for each requested platform and placement
  - At least one clear test matrix is included
  - Brand and claim review is complete
  - No launch or spend action is taken automatically
failure_modes:
  - same_copy_everywhere: "The output ignores platform context and repeats one version across surfaces"
  - weak_hook: "Openings fail to create attention or relevance for the audience"
  - generic_cta: "CTA is vague and not matched to funnel stage"
  - policy_risk: "Copy introduces claims or targeting language likely to violate platform rules"
validators:
  - type: platform_fit
    description: "Each requested platform has copy shaped to its placement constraints"
  - type: angle_consistency
    description: "Variants share a coherent message while testing distinct hooks"
  - type: brand_check
    description: "Output passes a brand compliance review"
estimated_tokens: 14000
---

# Social Campaign

## When to Use

Use this skill when a brief needs to become launch-ready social copy across one or more platforms without directly publishing anything.

Typical uses:

- New product or feature launches
- Paid social concept packages
- Organic promotion plans
- Campaign refreshes based on past winners

## Procedure

### 1. Establish the Campaign Objective

Extract the operating constraints from the task packet:

- Objective: awareness, traffic, leads, signups, purchases, or retention
- Offer and proof points
- Audience segment
- Requested platforms and placements
- Mandatory CTA or destination URL

If platforms are not specified, default to a small core set: Meta feed, Instagram Stories/Reels, LinkedIn feed, and X post/thread.

### 2. Gather Audience and Competitive Context

Collect context before writing:

```
marketing.get_audience_insights(platform, segment)
marketing.get_competitor_content(domain, content_type)
```

Look for:

- Audience pains, desires, and objections
- Offers or creative angles already saturated in the market
- Useful proof patterns: testimonials, stats, comparisons, demos

### 3. Define the Core Angle

Write the campaign spine first:

- Primary promise
- Supporting proof
- 3 to 5 hook directions
- CTA matched to funnel stage
- Guardrails for claims and tone

Do not generate dozens of variants until the campaign angle is internally consistent.

### 4. Create Platform Variants

Produce copy for each requested surface:

- Short, medium, and long variants when useful
- Placement-aware openings
- Caption/body length that fits the surface
- CTA wording adapted to the user intent on that platform

Where relevant, include a compact creative note describing the asset style that best matches the copy.

### 5. Build the Test Matrix

Return a structured test matrix instead of an undifferentiated list:

- Hook dimension
- Offer/proof dimension
- CTA dimension
- Recommended priority order

Aim for useful testing breadth, not arbitrary volume.

### 6. Run Compliance Review

Check the package before returning it:

```
marketing.check_brand_compliance(content, brand_guidelines)
```

Flag:

- Claim-risk language
- Missing proof for bold statements
- Tone drift
- Targeting phrasing likely to trigger policy issues

### 7. Optional Draft Campaign Packaging

If the task packet explicitly asks for platform-ready campaign structure, assemble a draft config:

```
marketing.create_draft_campaign(platform, campaign_config)
```

This skill may prepare a draft, but it must not publish or spend without an approval gate.

## Validation Checklist

- [ ] Campaign objective and audience are explicit
- [ ] Core angle is defined before variants
- [ ] Platform variants are meaningfully adapted
- [ ] Test matrix is structured and useful
- [ ] Compliance review is complete
- [ ] No direct launch action was taken
