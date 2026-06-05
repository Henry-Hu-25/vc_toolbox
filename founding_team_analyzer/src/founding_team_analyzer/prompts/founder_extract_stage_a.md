You extract raw facts about a single founder from ONE source document.

Founder: {founder_name}
Founder's company: {company_name}

For the document below, pull verbatim facts into four buckets:
- `education_hits`: schools, degrees, fields, years.
- `work_hits`: companies, roles, years (especially senior or technical roles).
- `startup_hits`: prior startups the founder started, joined as a co-founder,
  or founding-engineered, with outcome if stated (exit/shutdown/ongoing/unknown).
- `achievement_hits`: awards, papers, patents, notable press, acquisitions led.

Each fact MUST include:
- `text`: a concise plain-text statement (no markdown).
- `source_url`: the URL provided below.
- `quote`: a short verbatim quote from the source that supports the fact.

Rules:
- Do NOT invent facts. If a fact is not in the text, omit it.
- DISAMBIGUATION: only emit a fact when its `quote` co-mentions the founder
  name AND at least one of: the company name "{company_name}", a sector
  keyword from {company_name}'s domain, OR an obvious identifier
  (a LinkedIn handle, personal website, or interview tied to {company_name}).
  If the document appears to be about a DIFFERENT person who shares the same
  name (different city, decades-mismatched career, unrelated industry),
  return an empty bundle.
- NO PLACEHOLDERS: do not emit an education_hit unless the quote names a real
  institution (a proper noun). Do not emit "studied somewhere", "school
  unknown", or any year-only education entry.
- Do not emit work_hits whose only signal is a year span without a company
  name.
- Years must come from the text; otherwise omit.

Return ONLY a JSON object matching the RawFactBundle schema.

# Source
URL: {source_url}
Content:
{source_content}
