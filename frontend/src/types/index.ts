export type Tone = "positive" | "negative" | "neutral";
export type InsightKind = "negative" | "positive" | "opportunity";

export interface Merchant {
  merchant_id: string;
  name: string;
  owner_name: string;
  category: string;
  location: string;
  business_hours: string;
  as_of: string;
}

export interface ScoreDriver {
  label: string;
  value: string;
  tone: Tone;
}

export interface ComponentDetail {
  key: string;
  label: string;
  score: number;
  weight: number;
  weighted_points: number;
  status: string;
  summary: string;
  drivers: ScoreDriver[];
}

export interface HealthScore {
  overall_score: number;
  previous_score: number;
  change: number;
  status: string;
  trend: "declining" | "improving" | "steady";
  needs_attention: boolean;
  status_bands: { min: number; label: string }[];
  components: Record<string, number>;
  component_detail: ComponentDetail[];
  weights: Record<string, number>;
  base_weights: Record<string, number>;
  demand_fulfillment_included: boolean;
  demand_fulfillment_weight: number;
  comparable_basis: boolean;
  as_of: string;
}

export interface Insight {
  id: string;
  kind: InsightKind;
  title: string;
  change_percent: number;
  severity: "high" | "medium" | "low";
  description: string;
  impact_score: number;
  detail: Record<string, unknown>;
}

export interface TrendPoint {
  date: string;
  label: string;
  revenue: number;
  transactions: number;
}

export interface TodaySnapshot {
  date: string;
  revenue: number;
  revenue_change: number;
  transactions: number;
  transactions_change: number;
  average_transaction: number;
  average_transaction_change: number;
  unique_customers: number;
}

export interface Campaign {
  campaign_id: string;
  merchant_id: string;
  campaign_name: string;
  cashback_amount: number;
  minimum_transaction: number;
  start_time: string;
  end_time: string;
  target_segment: string;
  status: "ACTIVE" | "PAUSED";
  created_at: string;
  projection?: ScoreProjection;
}

export interface AiProvider {
  provider: "anthropic" | "openai" | "ollama" | "template";
  configured: string;
  label: string;
  model: string;
  llm_enabled: boolean;
}

export interface Dashboard {
  merchant: Merchant;
  health: HealthScore;
  today: TodaySnapshot;
  week: {
    revenue: number;
    revenue_change: number;
    transactions: number;
    transactions_change: number;
    average_transaction: number;
    average_transaction_change: number;
    customers: number;
  };
  revenue_trend: TrendPoint[];

  /** Transaction-side movements, ranked by impact on the score. */
  what_changed: Insight[];

  /** The half of the story the ledger cannot see. */
  shop_floor: ShopFloorSnapshot;

  /** The joined narrative: transaction signals paired with shop signals. */
  ai_summary: string;
  unified_insights: UnifiedInsight[];
  unified_counts: UnifiedPayload["counts"];

  active_campaign: Campaign | null;
  open_restock_alerts: RestockAlert[];
  ai_provider: AiProvider;

  /** Money in, money stuck, money out. */
  money: MoneyFlow;
  notifications: NotificationStatus;
}

export interface HourlyPoint {
  hour: number;
  label: string;
  current: number;
  baseline: number;
  change_percent: number;
}

export interface WeekdayPoint {
  date: string;
  day: string;
  revenue: number;
  historical_average: number;
  change_percent: number;
}

export interface InsightsPayload {
  insights: Insight[];
  negative: Insight[];
  positive: Insight[];
  opportunities: Insight[];
  headline: string;
  health: HealthScore;
  hourly_distribution: HourlyPoint[];
  weekday_comparison: WeekdayPoint[];
}

export interface ScoreProjection {
  label: string;
  current_score: number;
  projected_score: number;
  delta: number;
  projected_status: string;
  components_before: Record<string, number>;
  components_after: Record<string, number>;
  disclaimer: string;
  assumptions: string[];
}

export interface Recommendation {
  id: string;
  name: string;
  headline: string;
  objective: string;
  config: {
    cashback_amount: number;
    minimum_transaction: number;
    start_time: string;
    end_time: string;
    window_label: string;
    target_segment: string;
  };
  why_now: string;
  rationale: string[];
  evidence: Record<string, number>;
  projection: {
    label: string;
    disclaimer: string;
    recapture_rate: number;
    evening_transaction_lift_percent: number;
    revenue_per_day: number;
    revenue_per_week: number;
    estimated_cashback_cost_per_day: number;
    estimated_cashback_cost_per_week: number;
  };
  score_projection: ScoreProjection;
  already_active: boolean;
  cta: string;
}

export interface AskResponse {
  question: string;
  answer: string;
  provider: string;
  model: string;
  fallback_used: boolean;
  fallback_reason?: string;
  context_used: Record<string, number>;
  suggested_questions: string[];
}

export interface CampaignLaunchResponse {
  status: string;
  campaign_id: string;
  message: string;
  campaign: Campaign;
  projection: ScoreProjection;
}

/* ------------------------------------------------------ shop intelligence */

export type Availability = "available" | "out_of_stock" | "intermittent" | "unknown";
export type ShopIntent = "product_request" | "out_of_stock_report" | "suspicious_activity";

export interface ShopEvent {
  event_id: string;
  merchant_id: string;
  timestamp: string;
  hour: number;
  product: string;
  product_family: string;
  product_display: string;
  product_query: string;
  intent: ShopIntent;
  availability: Availability;
  potential_lost_sale: boolean;
  confidence: number;
  transcript: string;
  source: "audio" | "demo" | "manual";
  extractor: "rules" | "llm";
  fraud_signal: { marker: string; severity: string; reason: string } | null;
  interaction_id: string | null;
  interaction_outcome: string | null;
  buyer_intent: string | null;
  seller_response: string | null;
  quantity: number | null;
}

export interface ProductDemand {
  product: string;
  family: string;
  catalog_items: string[];
  requests: number;
  unfulfilled_requests: number;
  fulfilled_requests: number;
  unfulfilled_share: number;
  availability: Availability;
  potential_lost_sales: boolean;
  high_demand: boolean;
  peak_hour: number | null;
  hourly_requests: { hour: number; requests: number }[];
  first_seen: string | null;
  last_seen: string | null;
  average_confidence: number;
}

export interface HourlyDemandPoint {
  hour: number;
  label: string;
  requests: number;
  unfulfilled: number;
}

export interface ShopSummary {
  total_requests: number;
  unique_products: number;
  conversations_captured: number;
  unfulfilled_requests: number;
  high_demand_products: {
    product: string;
    requests: number;
    availability: Availability;
    peak_hour: number | null;
  }[];
  out_of_stock_requests: {
    product: string;
    requests: number;
    unfulfilled_requests: number;
    potential_lost_sales: boolean;
    estimated_lost_revenue: number | null;
  }[];
  products: ProductDemand[];
  hourly_demand: HourlyDemandPoint[];
  fraud_signals: {
    event_id: string;
    timestamp: string;
    transcript: string;
    marker?: string;
    severity?: string;
    reason?: string;
  }[];
  estimated_lost_revenue: number | null;
  lost_revenue_basis: string;
  window: { start: string; end: string; days: number };
  demo_mode: boolean;
  transcription: { available: boolean; engine: string | null; note: string };
}

export interface AiBoxCustomer {
  customer_id: string;
  name: string;
  balance: number;
}

export interface AiBoxActivity {
  event_id: string;
  event_type: string;
  confidence: number;
  /** Romanised Hinglish, whatever language it was spoken in. */
  transcript: string;
  /** The original, in the script it was spoken in. Absent for typed input. */
  transcript_spoken?: string;
  action_taken: boolean;
  changes: Record<string, string | number | boolean>;
  text_response: string;
  requires_confirmation: boolean;
  timestamp: string;
  voice?: AiBoxVoice;
  transcription?: AiBoxTranscription;
  /** Set when the mic opened but no speech came back; not an error. */
  heard_nothing?: boolean;
}

/** The spoken reply. `audio_data_uri` is present only for Sarvam Bulbul. */
export interface AiBoxVoice {
  available: boolean;
  mode: "sarvam" | "browser" | "mock";
  text: string;
  language_code?: string;
  audio_data_uri?: string;
  reason?: string;
}

/** What the recogniser heard, and in which language it decided it was. */
export interface AiBoxTranscription {
  engine: string | null;
  language: string | null;
  language_probability: number | null;
  is_mock: boolean;
  rejected: string | null;
}

export interface AiBoxSnapshot {
  device: { device_id: string; status: string; demo_mode: boolean };
  khata: {
    customers: AiBoxCustomer[];
    total_outstanding: number;
    customers_with_dues: number;
    overdue_accounts: number;
    activity: AiBoxActivity[];
    threshold: number;
  };
}

/* -------------------------------------------------------- unified insights */

export type UnifiedKind = "unified" | "shop" | "transaction";

export interface UnifiedInsight {
  id: string;
  kind: UnifiedKind;
  title: string;
  severity: "high" | "medium" | "low";
  confidence: number;
  impact_score: number;
  transaction_signal: {
    metric: string;
    change_percent: number;
    window: string | null;
    description: string;
  } | null;
  shop_signal: {
    product: string;
    requests: number;
    requests_in_window: number;
    unfulfilled_requests: number;
    availability: Availability;
    catalog_items: string[];
  } | null;
  explanation: string;
  recommended_actions: string[];
  evidence: Record<string, unknown>;
  correlation_note: string;
}

export interface UnifiedPayload {
  insights: UnifiedInsight[];
  headline: string;
  positive_signals: {
    id: string;
    metric: string;
    change_percent: number;
    description: string;
  }[];
  counts: {
    total: number;
    unified: number;
    shop_only: number;
    transaction_only: number;
  };
  methodology: { join: string; causation: string; max_confidence: number };
  health: HealthScore;
  hourly_distribution: HourlyPoint[];
  demand: ShopSummary;
  as_of: string;
}

/* ---------------------------------------------------------------- actions */

export interface RestockAlert {
  alert_id: string;
  merchant_id: string;
  product: string;
  catalog_items: string[];
  requests: number;
  unfulfilled_requests: number;
  estimated_lost_revenue: number | null;
  priority: string;
  status: "OPEN" | "RESOLVED";
  created_at: string;
}

export interface ActionProjection extends ScoreProjection {
  recovered_transactions_per_week?: number;
  recovered_revenue_per_week?: number;
}

export interface MerchantAction {
  type: "campaign" | "restock" | "combined";
  id: string;
  name: string;
  headline: string;
  objective: string;
  priority: string;
  projection: ActionProjection;
  cta: string;

  /* campaign */
  config?: Recommendation["config"];
  why_now?: string;
  rationale?: string[];
  campaign_projection?: Recommendation["projection"];
  already_active?: boolean;

  /* restock */
  product?: string;
  family?: string;
  catalog_items?: string[];
  evidence?: Record<string, number | string | null>;
  already_created?: boolean;

  /* combined */
  steps?: { order: number; action: string; title: string; detail: string }[];
  sequencing_note?: string;
}

export interface ActionPlan {
  actions: MerchantAction[];
  primary: MerchantAction;
  primary_type: MerchantAction["type"];
  campaign: Recommendation;
  restock_candidates: {
    product: string;
    family: string;
    requests: number;
    unfulfilled_requests: number;
    catalog_items: string[];
  }[];
  current_score: number;
  active_campaign: Campaign | null;
  open_restock_alerts: RestockAlert[];
}

export interface RestockResponse {
  status: string;
  alert_id: string;
  message: string;
  alert: RestockAlert;
  projection: ActionProjection;
}

/* ------------------------------------------------------ unified dashboard */

export interface ShopFloorSnapshot {
  total_requests: number;
  conversations_captured: number;
  unfulfilled_requests: number;
  unique_products: number;
  top_demand: {
    product: string;
    requests: number;
    availability: Availability;
    peak_hour: number | null;
  } | null;
  out_of_stock: ShopSummary["out_of_stock_requests"];
  estimated_lost_revenue: number | null;
  fraud_signals: number;
  demo_mode: boolean;
}

/* ------------------------------------------- buyer / seller intelligence */

export type SpeakerRole = "buyer" | "seller" | "unknown";

export type InteractionOutcome =
  | "fulfilled"
  | "unfulfilled"
  | "alternative_offered"
  | "abandoned"
  | "uncertain";

export interface ConversationTurn {
  speaker: SpeakerRole;
  confidence: number;
  text: string;
  intent: string | null;
  response: string | null;
  products: string[];
  quantity: number | null;
  price: number | null;
}

export interface Interaction {
  interaction_id: string;
  merchant_id: string;
  timestamp: string;
  hour: number;
  conversation: ConversationTurn[];
  product: string | null;
  product_family: string | null;
  catalog_item: string | null;
  quantity: number | null;
  price_mentioned: number | null;
  buyer_intent: string;
  seller_response: string;
  interaction_outcome: InteractionOutcome;
  potential_lost_sale: boolean;
  expects_transaction: boolean;
  confidence: number;
  role_confidence: number;
  transcript: string;
  source: string;
  extractor: string;
  reasoning: string[];
  fraud_signal: { marker: string; severity: string; reason: string } | null;
}

export interface OutcomeSummary {
  counts: Record<InteractionOutcome, number>;
  decided_interactions: number;
  total_interactions: number;
  fulfillment_rate: number | null;
  lost_sales: number;
  expected_transactions: number;
}

export interface DemandFulfillment {
  score: number;
  fulfillment_rate: number;
  decided_interactions: number;
  unfulfilled: number;
  products_short: number;
  chronic_shortages: {
    product: string;
    requests: number;
    unfulfilled_requests: number;
  }[];
  penalties: { repeat_shortage: number; breadth: number };
  summary: string;
  drivers: ScoreDriver[];
  method: string;
  sampling_caveat: string;
}

/* --------------------------------------------------- root cause analysis */

export interface DirectCause {
  id: string;
  category: "direct_evidence";
  title: string;
  component: string | null;
  component_label?: string;
  component_before?: number;
  component_after?: number;
  change_percent: number;
  points_lost: number;
  severity: "high" | "medium" | "low";
  confidence: number;
  confidence_band: string;
  evidence_type: string;
  detail: string;
  supporting_signals: {
    metric: string;
    change_percent: number;
    severity: string;
    description: string;
  }[];
}

export interface ContributingFactor {
  id: string;
  category: "possible_contributing_factor";
  title: string;
  product: string | null;
  requests: number;
  unfulfilled_requests: number;
  requests_in_declining_window: number;
  overlap_share_percent: number;
  severity: "high" | "medium" | "low";
  confidence: number;
  confidence_band: string;
  evidence_type: string;
  detail: string;
  correlation_note: string;
}

export interface ScoreAttributionRow {
  component: string;
  label: string;
  before: number;
  after: number;
  change: number;
  weight: number;
  points_contributed: number;
}

export interface RootCauseAnalysis {
  score: {
    current: number;
    previous: number;
    change: number;
    status: string;
    trend: string;
    comparable_basis: boolean;
  };
  narrative: string;
  direct_evidence: DirectCause[];
  possible_contributing_factors: ContributingFactor[];
  score_attribution: ScoreAttributionRow[];
  counts: { direct: number; contributing: number };
  methodology: {
    attribution: string;
    separation: string;
    confidence: Record<string, number>;
  };
  demand_fulfillment: DemandFulfillment | null;
  outcomes: OutcomeSummary;
  as_of: string;
}

/* --------------------------------------------------- transaction correlation */

export interface CorrelationResult {
  interaction_id: string;
  transaction_status:
    | "confirmed"
    | "possible_match"
    | "no_match"
    | "insufficient_data";
  matching_reason: string;
  confidence: number;
  matched_transaction: {
    transaction_id: string;
    timestamp: string;
    amount: number;
    seconds_from_interaction: number;
  } | null;
  candidates_in_window: number;
  window_seconds: number;
  data_limitation: string | null;
}

/* ------------------------------------------------------------- copilot */

export interface CopilotEvidence {
  metric: string;
  value: string;
  change: string;
  evidence_type: "observed" | "possible_contributing_factor";
}

export interface CopilotAnswer {
  question: string;
  answer: string;
  evidence: CopilotEvidence[];
  provider: string;
  model: string;
  fallback_used: boolean;
  fallback_reason?: string | null;
  suggested_questions: string[];
  disclaimer: string;
}

/* ------------------------------------------------------------ money flow */

export type ExpenseCategory =
  | "stock"
  | "utilities"
  | "rent"
  | "salary"
  | "transport"
  | "other";

export interface Expense {
  expense_id: string;
  merchant_id: string;
  amount: number;
  category: ExpenseCategory;
  label?: string;
  payee: string | null;
  transcript: string;
  source: string;
  recorded_at: string;
}

export interface CategoryTotal {
  category: ExpenseCategory;
  label: string;
  amount: number;
}

/**
 * The three columns a munim keeps. Only `money_in` comes from payments data;
 * the other two exist because the merchant said them out loud.
 */
export interface MoneyFlow {
  money_in: {
    today: number;
    today_change: number;
    week: number;
    week_change: number;
    transactions_today: number;
    customers_today: number;
    khata_collected: number;
    khata_collected_count: number;
    source: string;
  };
  money_stuck: {
    outstanding: number;
    customers_with_dues: number;
    top_debtors: { name: string; balance: number }[];
    largest: number;
    source: string;
  };
  money_out: {
    today: number;
    total: number;
    count: number;
    count_today: number;
    by_category: CategoryTotal[];
    recent: Expense[];
    source: string;
  };
  /** Demand that walked out unserved. An estimate, never added to a column. */
  at_risk: {
    estimated_lost_revenue: number | null;
    unfulfilled_requests: number;
    note: string;
  };
  net_today: number;
  verdict: string;
  as_of: string;
}

export interface NotificationStatus {
  configured: boolean;
  credentials_present: boolean;
  enabled: boolean;
  channel: "sms" | "whatsapp";
  from: string | null;
  to: string | null;
  missing: string[];
  note: string;
}

/* ------------------------------------------------------------ collections */

export interface KhataDebtor {
  customer_id: string;
  name: string;
  balance: number;
  phone: string | null;
  language: string;
  last_reminded_at: string | null;
  reminder_count: number;
}

export interface Reminder {
  reminder_id: string;
  customer_id: string;
  name: string;
  amount: number;
  channel: string;
  message: string;
  pay_link: string | null;
  delivered: boolean;
  detail: string;
  sent_at: string;
}

export interface CollectionsSnapshot {
  outstanding: KhataDebtor[];
  total_outstanding: number;
  chaseable: KhataDebtor[];
  missing_phone: string[];
  recent_reminders: Reminder[];
  languages: { key: string; label: string }[];
  cooldown_hours: number;
  pay_link_configured: boolean;
}
