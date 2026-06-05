You are filling in MISSING fields on an already-extracted Company record.

Current Company (JSON):
{current_company_json}

Missing fields to fill (only these): {missing_fields}

Use ONLY the new sources below. Do NOT contradict already-set fields; just fill
the missing ones if the sources explicitly support them. If a missing field is
not actually present in the sources, leave it null.

Return ONLY a JSON object matching the Company schema. Preserve the existing
values for fields that are NOT in the missing list (copy them through).

# New sources (focused on the missing fields)
{sources_block}
