import type {
  ActionPlan,
  CopilotAnswer,
  Interaction,
  OutcomeSummary,
  RootCauseAnalysis,
  AskResponse,
  Campaign,
  CampaignLaunchResponse,
  Dashboard,
  HealthScore,
  InsightsPayload,
  Recommendation,
  RestockAlert,
  RestockResponse,
  ShopEvent,
  ShopSummary,
  UnifiedPayload,
  AiBoxActivity,
  AiBoxSnapshot,
  MoneyFlow,
  Expense,
  CategoryTotal,
  CollectionsSnapshot,
  Reminder,
} from "@/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly hint?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "Can't reach the Business Health service.",
      undefined,
      "Start the backend with `uvicorn app.main:app --reload` in the backend directory.",
    );
  }

  return unwrap<T>(response);
}

/**
 * A multipart POST, for the one thing that is not JSON: recorded audio.
 *
 * Deliberately does NOT go through `request`, which sets a JSON content-type.
 * FormData needs the browser to set that header itself, because only the
 * browser knows the multipart boundary it generated.
 */
async function upload<T>(path: string, body: FormData): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      body,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "Can't reach the Business Health service.",
      undefined,
      "Start the backend with `uvicorn app.main:app --reload` in the backend directory.",
    );
  }

  return unwrap<T>(response);
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    let hint: string | undefined;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
      hint = body.hint;
    } catch {
      /* non-JSON error body, keep the status message */
    }
    throw new ApiError(detail, response.status, hint);
  }

  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  healthScore: () => request<HealthScore>("/api/health-score"),
  insights: () => request<InsightsPayload>("/api/insights"),
  unifiedInsights: () => request<UnifiedPayload>("/api/insights/unified"),
  recommendation: () => request<Recommendation>("/api/recommendation"),
  actions: () => request<ActionPlan>("/api/actions"),
  campaigns: () =>
    request<{ campaigns: Campaign[]; active: Campaign | null }>("/api/campaigns"),

  /* ---- money in / stuck / out ---- */

  moneyFlow: () => request<MoneyFlow>("/api/money-flow"),

  expenses: (limit = 50) =>
    request<{
      expenses: Expense[];
      totals: {
        total: number;
        today: number;
        count: number;
        count_today: number;
        by_category: CategoryTotal[];
        recent: Expense[];
      };
      categories: { key: string; label: string }[];
    }>(`/api/expenses?limit=${limit}`),

  recordExpense: (payload: {
    amount: number;
    note: string;
    category?: string;
    payee?: string;
  }) =>
    request<{ status: string; expense_id: string; message: string; expense: Expense }>(
      "/api/expenses",
      { method: "POST", body: JSON.stringify(payload) },
    ),

  /* ---- collections: chasing money that is stuck ---- */

  collections: () => request<CollectionsSnapshot>("/api/collections"),

  /**
   * Chase one customer. Three outcomes matter and they are different:
   * 201 sent, 409 refused on purpose (settled / cooldown / no number),
   * 502 tried and the channel failed. The caller shows the reason either way.
   */
  remind: (customer: string, force = false) =>
    request<{ status: string; reminder: Reminder }>("/api/collections/remind", {
      method: "POST",
      body: JSON.stringify({ customer, force }),
    }),

  setContact: (customer: string, phone?: string, language?: string) =>
    request<{ status: string; customer: Record<string, unknown> }>(
      "/api/collections/contact",
      { method: "POST", body: JSON.stringify({ customer, phone, language }) },
    ),

  /* ---- shop floor ---- */

  shopSummary: () => request<ShopSummary>("/api/shop-intelligence/summary"),

  shopEvents: (limit = 60) =>
    request<{ events: ShopEvent[]; total: number; returned: number; demo_mode: boolean }>(
      `/api/shop-intelligence/events?limit=${limit}`,
    ),

  shopStatus: () => request<Record<string, unknown>>("/api/shop-intelligence/status"),

  shopInteractions: (limit = 40) =>
    request<{
      interactions: Interaction[];
      total: number;
      returned: number;
      outcomes: OutcomeSummary;
    }>(`/api/shop-intelligence/interactions?limit=${limit}`),

  aiBoxState: () => request<AiBoxSnapshot>("/api/ai-box/state"),
  aiBoxStatus: (status: string, device_id = "demo-box") =>
    request<AiBoxSnapshot["device"]>("/api/ai-box/status", {
      method: "POST",
      body: JSON.stringify({ status, device_id }),
    }),
  processAiBox: (transcript: string, source = "demo") =>
    request<AiBoxSnapshot["khata"]["activity"][number]>("/api/ai-box/process", {
      method: "POST",
      body: JSON.stringify({ transcript, source }),
    }),

  /**
   * Recorded speech in, a finished action out.
   *
   * No language is sent. The backend detects it, which is the whole point of
   * this endpoint existing alongside `processAiBox`: the browser's own
   * recogniser has to be told a language up front and has no Odia model at
   * all, so anything but Hindi died before it reached the books.
   */
  processAiBoxVoice: (audio: Blob, deviceId = "dashboard-mic") => {
    const form = new FormData();
    form.append("audio", audio, "clip.wav");
    form.append("device_id", deviceId);
    // No content-type header: the browser must set the multipart boundary.
    return upload<AiBoxActivity>("/api/ai-box/voice", form);
  },
  confirmAiBox: (eventId: string) => request<AiBoxSnapshot["khata"]["activity"][number]>(`/api/ai-box/confirm/${eventId}`, { method: "POST" }),
  rejectAiBox: (eventId: string) => request<{ success: boolean; message: string }>(`/api/ai-box/reject/${eventId}`, { method: "POST" }),
  resetAiBox: () => request<AiBoxSnapshot>("/api/ai-box/reset", { method: "POST" }),

  /* ---- root cause + copilot ---- */

  rootCause: () => request<RootCauseAnalysis>("/api/root-cause-analysis"),

  askCopilot: (question: string) =>
    request<CopilotAnswer>("/api/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  seedShopDemo: () =>
    request<{ status: string; events_created: number; message: string }>(
      "/api/shop-intelligence/demo/seed",
      { method: "POST" },
    ),

  /** Feed a transcript straight into the pipeline: no microphone needed. */
  sendTranscript: (transcript: string) =>
    request<{ success: boolean; transcript: string; events: ShopEvent[]; event_count: number }>(
      "/api/shop-intelligence/text",
      { method: "POST", body: JSON.stringify({ transcript }) },
    ),

  /* ---- actions ---- */

  restockAlerts: () =>
    request<{ alerts: RestockAlert[]; open: RestockAlert[] }>("/api/restock-alerts"),

  createRestockAlert: (product: string) =>
    request<RestockResponse>("/api/restock-alerts", {
      method: "POST",
      body: JSON.stringify({ product }),
    }),

  ask: (question: string) =>
    request<AskResponse>("/api/ask-ai", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  launchCampaign: (payload: {
    merchant_id: string;
    campaign_name: string;
    cashback_amount: number;
    minimum_transaction: number;
    start_time: string;
    end_time: string;
    target_segment?: string;
  }) =>
    request<CampaignLaunchResponse>("/api/campaigns", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  resetDemo: () => request<{ status: string }>("/api/demo/reset", { method: "POST" }),
};
