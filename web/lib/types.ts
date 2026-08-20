// Mirrors the Pydantic schemas in founding_team_analyzer/schemas.py.

export type Confidence = "high" | "medium" | "low";
export type Strength = "strong" | "medium" | "weak" | "none";
export type Tier = "Strong" | "Promising" | "Mixed" | "Weak";

export interface Company {
  name: string;
  website: string | null;
  linkedin_url: string | null;
  one_liner: string | null;
  sector: string | null;
  sub_sector: string | null;
  hq_location: string | null;
  founded_year: number | null;
  stage_signals: string[];
  source_urls: string[];
}

export interface Education {
  school: string;
  degree: string | null;
  field: string | null;
  start_year: number | null;
  end_year: number | null;
  source_urls: string[];
}

export interface WorkExperience {
  company: string;
  role: string;
  start_year: number | null;
  end_year: number | null;
  is_founder_role: boolean;
  is_technical_role: boolean;
  source_urls: string[];
}

export interface PriorStartup {
  name: string;
  role: string;
  outcome: "exit" | "shutdown" | "ongoing" | "unknown";
  year_started: number | null;
  source_urls: string[];
}

export interface FounderProfile {
  name: string;
  current_title: string;
  linkedin_url: string | null;
  education: Education[];
  work: WorkExperience[];
  prior_startups: PriorStartup[];
  accelerators: string[];
  notable_achievements: string[];
  total_years_experience: number | null;
  domain_years_experience: number | null;
  confidence: Confidence;
  missing_fields: string[];
  source_urls: string[];
}

export interface SharedSchool {
  school: string;
  overlap_years: string | null;
}

export interface SharedEmployer {
  company: string;
  overlap_years: string | null;
  same_technical_cluster: boolean;
}

export interface FounderPairOverlap {
  founder_a: string;
  founder_b: string;
  shared_schools: SharedSchool[];
  shared_employers: SharedEmployer[];
  shared_prior_startups: string[];
  shared_accelerators: string[];
  narrative: string;
  strength: Strength;
}

export interface TeamOverlap {
  pairs: FounderPairOverlap[];
  overall_strength: Strength;
  notes: string[];
}

export interface CriterionScore {
  key: string;
  label: string;
  weight: number;
  score: number;
  evidence: string[];
  rationale: string;
}

export interface RubricCriterion {
  key: string;
  label: string;
  weight: number;
  anchor_0: string;
  anchor_3: string;
  anchor_5: string;
  required_evidence: string;
}

export interface RubricPayload {
  criteria: RubricCriterion[];
}

export interface TeamScore {
  criteria: CriterionScore[];
  overall_0_100: number;
  tier: Tier;
  top_strengths: string[];
  top_risks: string[];
  open_questions: string[];
}

export interface CostLedger {
  llm_calls: number;
  tavily_searches: number;
  tavily_extracts: number;
  http_fetches: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ReportPayload {
  generated_at: string;
  raw_input: string;
  company: Company | null;
  founders: FounderProfile[];
  overlaps: TeamOverlap | null;
  score: TeamScore | null;
  warnings: string[];
  cost: CostLedger | null;
}

export type RunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface RunSummary {
  slug: string | null;
  run_id?: string;
  generated_at: string | null;
  company_name: string;
  tier: Tier | null;
  overall_0_100: number | null;
  raw_input: string | null;
  modified_at: string;
  status?: RunStatus;
}

export type EventType =
  | "run_started"
  | "node_started"
  | "node_finished"
  | "warning"
  | "cost_update"
  | "done"
  | "error";

export interface StreamEvent {
  type: EventType;
  ts: string;
  payload: Record<string, unknown>;
}
