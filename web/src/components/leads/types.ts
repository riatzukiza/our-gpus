export type LeadStatus =
  | "new"
  | "reviewed"
  | "approved"
  | "suppressed"
  | "exported";

export type RecommendedRoute =
  | "security_txt"
  | "rdap_abuse"
  | "website_security"
  | "website_general"
  | "provider_abuse"
  | "manual_review";

export interface AssetSummary {
  id: string;
  ip?: string | null;
  hostname?: string | null;
  domain?: string | null;
  port?: number | null;
  protocol?: string | null;
  service?: string | null;
  country_code?: string | null;
  region?: string | null;
  city?: string | null;
  last_seen?: string | null;
}

export interface ContactResponse {
  id: string;
  organization_id?: string | null;
  domain_id?: string | null;
  contact_type: string;
  value: string;
  source_type: string;
  source_url?: string | null;
  is_role_account?: boolean;
  confidence?: number;
  last_verified_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface OrgCandidateResponse {
  id: string;
  organization_id?: string | null;
  name: string;
  normalized_name: string;
  score: number;
  org_conflict_penalty: number;
  rationale: Array<Record<string, unknown>>;
  last_evaluated_at?: string | null;
}

export interface OrgResolutionResponse {
  id: string;
  organization_id?: string | null;
  winning_org_candidate_id?: string | null;
  resolution_mode: string;
  confidence: number;
  rationale: Array<Record<string, unknown>>;
  resolved_at: string;
  reviewed_at?: string | null;
  reviewer_note?: string | null;
  org_candidates: OrgCandidateResponse[];
}

export interface LeadScoreBreakdown {
  confidence_score: number;
  org_confidence: number;
  contact_quality: number;
  route_legitimacy: number;
  org_conflict_penalty: number;
}

export interface LeadContactCandidateResponse {
  id: string;
  contact_id: string;
  route: RecommendedRoute;
  rank: number;
  score: number;
  org_confidence: number;
  contact_quality: number;
  route_legitimacy: number;
  org_conflict_penalty: number;
  rationale: Array<Record<string, unknown>>;
  last_evaluated_at: string;
  contact?: ContactResponse | null;
}

export interface EvidenceSupport {
  asset_id?: string | null;
  domain_id?: string | null;
  organization_id?: string | null;
  asn_id?: string | null;
  contact_id?: string | null;
}

export interface EvidenceStepResponse {
  id: string;
  raw_fetch_id?: string | null;
  kind: string;
  source_type: string;
  source_url?: string | null;
  raw_value?: string | null;
  normalized_value?: string | null;
  confidence: number;
  weight: number;
  observed_at: string;
  supports: EvidenceSupport;
  metadata?: Record<string, unknown>;
}

export interface LeadRecordResponse {
  id: string;
  asset_id: string;
  organization_id?: string | null;
  org_resolution_id?: string | null;
  primary_contact_id?: string | null;
  status: LeadStatus;
  recommended_route?: RecommendedRoute | null;
  notes?: string | null;
  scorer_version?: string | null;
  resolver_version?: string | null;
  created_at: string;
  updated_at: string;
  last_resolved_at?: string | null;
  asset?: AssetSummary | null;
  organization?: OrgResolutionResponse | null;
  primary_contact?: ContactResponse | null;
  scores: LeadScoreBreakdown;
  contact_candidates: LeadContactCandidateResponse[];
  evidence_steps: EvidenceStepResponse[];
}

export interface PaginatedLeadRecordResponse {
  items: LeadRecordResponse[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface CampaignClusterResponse {
  id: string;
  cluster_type: string;
  cluster_key: string;
  geo_region?: string | null;
  org_density?: number | null;
  lead_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EnrichmentRunResponse {
  asset_id: string;
  rdap_status: string;
  ptr_status: string;
  tls_ct_status: string;
  security_txt_status: string;
  contact_page_status: string;
  last_error_by_source: Record<string, unknown>;
  source_versions: Record<string, string>;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  updated_at?: string | null;
}

export interface JobQueuedResponse {
  job_id: string;
  job_type: string;
  status: string;
  scheduled_at?: string | null;
  worker_hint?: string | null;
}

export interface AssetImportResponse {
  imported_count: number;
  created_count: number;
  updated_count: number;
  asset_ids: string[];
  lead_record_ids: string[];
}
