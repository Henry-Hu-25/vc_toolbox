"""Pydantic v2 schemas shared across nodes and used as LLM structured-output targets."""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


Confidence = Literal["high", "medium", "low"]
Strength = Literal["strong", "medium", "weak", "none"]
Tier = Literal["Strong", "Promising", "Mixed", "Weak"]


def _coerce_urls(value: list[str] | None) -> list[str]:
    return [u for u in (value or []) if isinstance(u, str) and u.strip()]


_PLACEHOLDER_RE = re.compile(
    r"^\s*("
    r"unspecified|unknown|n\.?\s*/?\s*a|none|null|placeholder|"
    r"school|university|college|institution|company|employer|"
    r"various|multiple"
    r")\b",
    re.IGNORECASE,
)
_NON_ALPHA_RE = re.compile(r"[^a-zA-Z]")


def is_placeholder_name(value: str | None) -> bool:
    """Return True for clearly junk institution/company names."""
    if value is None:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    if _PLACEHOLDER_RE.match(stripped):
        return True
    alpha = _NON_ALPHA_RE.sub("", stripped)
    if len(alpha) < 3:
        return True
    return False


class Company(BaseModel):
    name: str
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    one_liner: Optional[str] = None
    sector: Optional[str] = None
    sub_sector: Optional[str] = None
    hq_location: Optional[str] = None
    founded_year: Optional[int] = None
    employee_count: Optional[int] = None
    stage_signals: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @field_validator("source_urls", "stage_signals", mode="before")
    @classmethod
    def _clean_lists(cls, v):
        return _coerce_urls(v) if isinstance(v, list) else []


class Founder(BaseModel):
    name: str
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    source_urls: list[str] = Field(default_factory=list)


class FounderList(BaseModel):
    """Wrapper for structured-output: list[Founder]."""

    founders: list[Founder] = Field(default_factory=list)


class Education(BaseModel):
    school: str
    degree: Optional[str] = None
    field: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    source_urls: list[str] = Field(default_factory=list)


class WorkExperience(BaseModel):
    company: str
    role: str
    start_year: Optional[int] = None
    end_year: Optional[int] = None  # None = current
    is_founder_role: bool = False
    is_technical_role: bool = False
    source_urls: list[str] = Field(default_factory=list)


class PriorStartup(BaseModel):
    name: str
    role: str
    outcome: Literal["exit", "shutdown", "ongoing", "unknown"] = "unknown"
    year_started: Optional[int] = None
    source_urls: list[str] = Field(default_factory=list)


class RawFact(BaseModel):
    text: str
    source_url: str
    quote: Optional[str] = None


class RawFactBundle(BaseModel):
    education_hits: list[RawFact] = Field(default_factory=list)
    work_hits: list[RawFact] = Field(default_factory=list)
    startup_hits: list[RawFact] = Field(default_factory=list)
    achievement_hits: list[RawFact] = Field(default_factory=list)


class FounderProfile(BaseModel):
    name: str
    current_title: str
    linkedin_url: Optional[str] = None
    education: list[Education] = Field(default_factory=list)
    work: list[WorkExperience] = Field(default_factory=list)
    prior_startups: list[PriorStartup] = Field(default_factory=list)
    accelerators: list[str] = Field(default_factory=list)
    notable_achievements: list[str] = Field(default_factory=list)
    total_years_experience: Optional[int] = None
    domain_years_experience: Optional[int] = None
    confidence: Confidence = "low"
    missing_fields: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _scrub_placeholders_and_detect_collisions(self) -> "FounderProfile":
        self.education = [
            e for e in self.education if not is_placeholder_name(e.school)
        ]
        self.work = [
            w for w in self.work if not is_placeholder_name(w.company)
        ]
        self.prior_startups = [
            s for s in self.prior_startups if not is_placeholder_name(s.name)
        ]
        # Collision detector: implausibly broad histories suggest the researcher
        # merged multiple people with the same name. Downgrade confidence and
        # tag the issue so downstream nodes / the report can flag it.
        flags: list[str] = []
        if self.total_years_experience is not None and self.total_years_experience > 25:
            flags.append("profile_breadth_suspicious")
        if len(self.work) > 8:
            flags.append("profile_breadth_suspicious")
        starts = [w.start_year for w in self.work if w.start_year is not None]
        ends = [w.end_year for w in self.work if w.end_year is not None]
        if starts and ends and (max(ends) - min(starts)) > 30:
            flags.append("profile_breadth_suspicious")
        # Overlapping non-founder employments at different companies.
        non_founder = [w for w in self.work if not w.is_founder_role]
        for i, a in enumerate(non_founder):
            for b in non_founder[i + 1 :]:
                if a.company.strip().lower() == b.company.strip().lower():
                    continue
                a_s = a.start_year or 0
                a_e = a.end_year or 9999
                b_s = b.start_year or 0
                b_e = b.end_year or 9999
                if a_s and b_s and max(a_s, b_s) <= min(a_e, b_e):
                    flags.append("overlapping_employment_conflict")
                    break
            else:
                continue
            break
        if flags:
            self.confidence = "low"
            for f in flags:
                if f not in self.missing_fields:
                    self.missing_fields.append(f)
        return self


class SharedSchool(BaseModel):
    school: str
    overlap_years: Optional[str] = None  # e.g. "2014-2016"


class SharedEmployer(BaseModel):
    company: str
    overlap_years: Optional[str] = None
    same_technical_cluster: bool = False


class FounderPairOverlap(BaseModel):
    founder_a: str
    founder_b: str
    shared_schools: list[SharedSchool] = Field(default_factory=list)
    shared_employers: list[SharedEmployer] = Field(default_factory=list)
    shared_prior_startups: list[str] = Field(default_factory=list)
    shared_accelerators: list[str] = Field(default_factory=list)
    narrative: str = ""
    strength: Strength = "none"


class TeamOverlap(BaseModel):
    pairs: list[FounderPairOverlap] = Field(default_factory=list)
    overall_strength: Strength = "none"
    notes: list[str] = Field(default_factory=list)


class CriterionScore(BaseModel):
    key: str
    label: str
    weight: float
    score: int = Field(ge=0, le=5)
    evidence: list[str] = Field(default_factory=list)
    rationale: str


class TeamScore(BaseModel):
    criteria: list[CriterionScore]
    overall_0_100: float = 0.0
    tier: Tier = "Mixed"
    top_strengths: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CostLedger(BaseModel):
    llm_calls: int = 0
    tavily_searches: int = 0
    tavily_extracts: int = 0
    http_fetches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def merged(self, other: "CostLedger") -> "CostLedger":
        return CostLedger(
            llm_calls=self.llm_calls + other.llm_calls,
            tavily_searches=self.tavily_searches + other.tavily_searches,
            tavily_extracts=self.tavily_extracts + other.tavily_extracts,
            http_fetches=self.http_fetches + other.http_fetches,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


__all__ = [
    "Company",
    "Founder",
    "FounderList",
    "Education",
    "WorkExperience",
    "PriorStartup",
    "RawFact",
    "RawFactBundle",
    "FounderProfile",
    "SharedSchool",
    "SharedEmployer",
    "FounderPairOverlap",
    "TeamOverlap",
    "CriterionScore",
    "TeamScore",
    "CostLedger",
    "Confidence",
    "Strength",
    "Tier",
]
