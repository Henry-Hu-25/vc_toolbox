You consolidate multiple RawFactBundles about ONE founder into a single
FounderProfile.

Founder: {founder_name}
Authoritative current title (from the company's own team page): {founder_title}
Founder's current company: {company_name}

Inputs (a JSON array of RawFactBundles):
{bundles_json}

Rules:
- Use `{founder_title}` as `current_title`. Do NOT overwrite it unless a source
  whose URL contains "{company_name}"'s own domain explicitly contradicts it.
  Never copy a co-founder's title onto this founder.
- Deduplicate facts that describe the same education/job/startup.
- Order `education` and `work` chronologically (oldest first).
- For each Education/WorkExperience/PriorStartup item, include `source_urls`
  containing every source URL that supports any of its fields.
- DISAMBIGUATION: Before accepting any WorkExperience, verify that the
  supporting source URLs co-mention the founder's name. If you see two
  non-founder employments at DIFFERENT companies whose start/end years overlap,
  this is a strong signal that the researcher merged two different people who
  share a name. In that case, keep ONLY the employments supported by the
  most authoritative source (LinkedIn URL belonging to {founder_name} when
  available) and drop the others. If still ambiguous, set `confidence="low"`.
- NO PLACEHOLDERS: drop any education entry whose `school` is not a real,
  named institution (e.g. "Unspecified Institution", "Unknown", "various").
  Drop work entries whose `company` is missing or a placeholder.
- Resolve conflicts by preferring more authoritative sources in this order:
  LinkedIn > Crunchbase > company "about" page > press articles > blogs.
- Set `is_founder_role=true` on a WorkExperience whose role contains
  founder/co-founder/founding member.
- Set `is_technical_role=true` if the role is engineer, researcher, ML, data,
  CTO, VPE, principal/staff engineer, or similar technical IC/leadership.
- `accelerators` are short strings like "YC W21", "Techstars NYC 2019".
- Compute `total_years_experience` as years from the earliest work `start_year`
  to today (or the latest known end year). If unknown, leave null. If the
  number would be greater than 25 for an early-stage startup founder, this is
  a red flag - double-check that the underlying work entries actually belong
  to the same person; drop suspicious ones.
- Compute `domain_years_experience` as years of work in the current company's
  sector. If unclear, leave null.
- `confidence`:
  * `high` if we have LinkedIn + at least one other authoritative source.
  * `medium` if we have at least 2 sources of any kind with consistent data.
  * `low` if we have 0-1 sources, contradictions remain, or you detected a
    possible name collision.
- `missing_fields` lists any of:
  ["education", "work", "prior_startups", "accelerators",
   "total_years_experience", "domain_years_experience"]
  that have no supporting data.
- Never invent. If a field is unknown, leave it null / empty.

Return ONLY a JSON object matching the FounderProfile schema.
