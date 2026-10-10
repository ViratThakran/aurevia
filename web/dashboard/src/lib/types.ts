/**
 * Shapes of the API responses that the OpenAPI schema leaves untyped (they are returned as
 * free-form JSON objects). Kept in one place and matched to the backend code that builds them:
 * analytics/service.py, api/v1/analytics.py and api/v1/platform.py.
 */

export interface AnalyticsSummary {
  period: { start: string; end: string; campaign_id: string | null };
  activity: {
    calls: number;
    by_status: Record<string, number>;
    by_channel: Record<string, number>;
    connected: number;
    completed: number;
    failed: number;
    phone_answer_rate: number | null;
    avg_call_seconds: number | null;
    avg_turns: number | null;
  };
  sales: {
    meetings_booked: number;
    followups_scheduled: number;
    interested: number;
    not_interested: number;
    handoffs: number;
    do_not_call_requests: number;
    meetings_per_connected_call: number | null;
  };
  ai_quality: {
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
    latency_target_met: boolean | null;
    interrupted_turn_rate: number | null;
    tool_calls: number;
    tool_failure_rate: number | null;
    tool_rejection_rate: number | null;
    escalations: number;
  };
  economics: {
    cost: Record<string, string>;
    fully_priced: boolean;
    cost_per_call: Record<string, string> | null;
    cost_per_meeting: Record<string, string> | null;
  };
}

export interface PlanLimits {
  plan_name: string;
  monthly_call_limit: number | null;
  monthly_minute_limit: number | null;
  monthly_cost_limit: string | null;
  cost_currency: string | null;
  max_concurrent_calls: number;
}

export interface UsageReport {
  month_start: string;
  plan: PlanLimits;
  used: { calls: number; minutes: number; concurrent_calls: number; cost: string | null };
  resources: { resource: string; quantity: string; unpriced_quantity: string; cost: Record<string, string> }[];
  cost: Record<string, string>;
  fully_priced: boolean;
}

export interface PlatformTenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  created_at: string;
  members: number;
  calls_this_month: number;
  last_call_at: string | null;
}

export interface PlatformPlan extends PlanLimits {
  default: boolean;
  updated_at?: string;
}

export interface PlatformPrice {
  id: string;
  provider: string;
  resource: string;
  model: string;
  currency: string;
  amount: string;
  per_quantity: number;
  effective_from: string;
}

export const PERMISSIONS = [
  ["calls.place", "Place calls (test, phone, campaign)"],
  ["leads.manage", "Create and edit leads, consent"],
  ["leads.privacy", "Export or erase personal data"],
  ["campaigns.manage", "Manage campaigns and auto-dialing"],
  ["agents.manage", "Configure the AI agent"],
  ["numbers.manage", "Phone numbers and test numbers"],
  ["compliance.manage", "Compliance policy settings"],
  ["team.manage", "Invite people, roles and members"],
  ["audit.read", "Read the audit log"],
  ["analytics.read", "Analytics, usage and cost"],
] as const;

export function money(amounts: Record<string, string> | null | undefined): string {
  if (!amounts || Object.keys(amounts).length === 0) return "—";
  return Object.entries(amounts)
    .map(([currency, amount]) => `${currency} ${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`)
    .join(" + ");
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}
