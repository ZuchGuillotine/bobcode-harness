---
id: seo_content_v1
name: SEO Content
version: "1.0"
domain: marketing
scope: content_draft
triggers:
  - seo
  - article
  - blog
  - keyword
  - landing page
  - organic traffic
agent_role: worker
allowed_tools:
  - marketing.get_search_keywords
  - marketing.get_analytics_summary
  - marketing.get_competitor_content
  - marketing.check_brand_compliance
  - marketing.create_content_draft
inputs:
  - task_packet: "Bounded plan including topic, audience, offer, desired conversion event, and target URL or property"
  - brand_guidelines: "Voice, claims, prohibited language, and required proof points"
  - existing_metrics: "Optional baseline CTR, rankings, page engagement, or conversion metrics"
outputs:
  - content_brief: "Search-informed brief with keyword cluster, angle, outline, and CTA"
  - draft: "SEO-ready draft with title options, metadata, headers, and internal-link suggestions"
  - optimization_notes: "On-page improvements, schema ideas, and refresh opportunities"
  - compliance_report: "Brand and claim-risk review for the draft"
definition_of_done:
  - Search intent is identified for the primary keyword cluster
  - Keyword recommendations are grouped by intent, not dumped as a flat list
  - Draft has a clear conversion goal and CTA
  - Title, meta description, and header structure are included
  - Claims and tone are checked against brand guidelines
failure_modes:
  - keyword_stuffing: "Draft over-optimizes for exact-match terms and harms readability"
  - wrong_intent: "Content format does not match the dominant search intent"
  - weak_conversion_path: "Draft attracts traffic but does not guide the reader to the next step"
  - unsupported_claims: "Draft makes claims that are not supported by provided evidence"
validators:
  - type: intent_check
    description: "Primary keyword, page type, and search intent are explicitly aligned"
  - type: metadata_check
    description: "Draft includes title, meta description, slug suggestion, and H1/H2 structure"
  - type: brand_check
    description: "Tone and claims pass brand compliance review"
estimated_tokens: 12000
---

# SEO Content

## When to Use

Use this skill when the task is to create or refresh search-oriented content that should earn qualified traffic and convert it into a measurable next step.

Typical uses:

- Blog posts and resource articles
- Landing pages and solution pages
- Existing content refreshes
- Search-informed briefs for human writers

Do not use this skill for:

- Pure social copy with no search intent
- Paid-ad creative testing
- Long-form thought leadership that is intentionally not search-targeted

## Procedure

### 1. Frame the Conversion Goal

Extract the page objective from the task packet:

- Primary conversion event
- Target audience segment
- Offer or product being promoted
- Geographic or vertical constraints

If the task lacks a concrete CTA, propose one before drafting.

### 2. Gather Search Evidence

Pull search and site context:

1. Query keyword opportunities:
   ```
   marketing.get_search_keywords(property_id, date_range, filters)
   ```
2. Review current analytics to understand existing winners and gaps:
   ```
   marketing.get_analytics_summary(platform, property_id, date_range, dimensions)
   ```
3. Sample competing content patterns:
   ```
   marketing.get_competitor_content(domain, content_type)
   ```

Group findings into:

- Primary keyword cluster
- Secondary supporting clusters
- Search intent category: informational, comparison, solution-seeking, or transactional
- Content gaps and differentiation angles

### 3. Build the Brief

Create a brief before writing the draft:

- Working title and target URL/slug
- Audience problem and desired outcome
- Recommended format and outline
- Proof points, examples, or product details to include
- Internal links or adjacent topics worth referencing
- CTA placement strategy

If evidence suggests a page refresh is stronger than a net-new draft, say so explicitly.

### 4. Draft the Content

Use the brief to create a search-ready draft:

- 3 title options
- Meta title and meta description
- H1 and H2/H3 structure
- Opening that matches the identified intent quickly
- Body sections that resolve the user's question without filler
- CTA section tied to the offer in the task packet

Prefer concise, evidence-backed language over generic SEO phrasing.

### 5. Check Brand and Claim Safety

Run a compliance pass:

```
marketing.check_brand_compliance(content, brand_guidelines)
```

Flag:

- Unsupported claims
- Regulated or risky language
- Tone drift from the brand voice
- Missing disclaimers or proof points

### 6. Return Optimization Notes

Include short, practical follow-ups:

- Refresh opportunities for existing pages
- Internal links to add
- Schema or FAQ opportunities
- Suggested tests for titles, intros, or CTAs

## Validation Checklist

- [ ] Primary keyword cluster is clear and intent-aligned
- [ ] Draft structure matches the recommended page type
- [ ] Metadata and headings are included
- [ ] CTA is specific and tied to the task objective
- [ ] Brand compliance review is complete
- [ ] Output is readable and not keyword-stuffed
