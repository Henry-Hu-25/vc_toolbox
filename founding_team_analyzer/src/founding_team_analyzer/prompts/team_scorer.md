You are scoring an early-stage startup founding team against an explicit rubric.

# Rubric

{rubric_table}

# Output rules

- For EACH of the 8 criteria above, emit a CriterionScore with:
  * `key`: exact key from the rubric (e.g. "founder_market_fit").
  * `label`: short human label.
  * `weight`: weight from the rubric (as a fraction, e.g. 0.20).
  * `score`: integer 0-5, calibrated to the anchors.
  * `evidence`: 1-3 short bullets, each containing a source URL from the dossier.
  * `rationale`: one line explaining the score.
- DO NOT compute the overall score; leave `overall_0_100=0` and `tier="Mixed"`
  (the host program computes those).
- Populate `top_strengths` (3-5 bullets), `top_risks` (3-5 bullets), and
  `open_questions` (3-7 due-diligence questions a VC would ask next).
- Be calibrated, not generous. A solo founder with no domain experience should
  score low even if the company looks promising.
- Every evidence bullet MUST cite a source URL that appears somewhere in the
  dossier. Do not invent URLs.

Return ONLY a JSON object matching the TeamScore schema.

# Dossier

{dossier}
