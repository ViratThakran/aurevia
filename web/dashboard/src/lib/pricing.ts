// Usage that has no price yet: left out of the cost, and counted as zero by the spend limit.

export interface UnpricedUsage {
  resource: string;
  unpriced_quantity: string;
}

/** "500,000 AI model: output tokens; 1,200 Voice: characters spoken", or "" when all priced. */
export function describeUnpriced(items: UnpricedUsage[] | undefined, labels: Record<string, string> = {}): string {
  return (items ?? [])
    .filter((u) => Number(u.unpriced_quantity) > 0)
    .map((u) => `${Number(u.unpriced_quantity).toLocaleString("en-IN")} ${labels[u.resource] ?? u.resource}`)
    .join("; ");
}

/** The warning shown with a cost figure; null when every unit of usage is priced. */
export function unpricedWarning(
  items: UnpricedUsage[] | undefined,
  { spendLimit = false, labels = {} }: { spendLimit?: boolean; labels?: Record<string, string> } = {},
): string | null {
  const detail = describeUnpriced(items, labels);
  if (!detail) return null;
  const effect = spendLimit
    ? "It counts as zero toward the monthly spend limit, so spend may pass the limit without stopping calls."
    : "The cost shown leaves it out.";
  return `No price is set for: ${detail}. ${effect} Add the prices in Platform admin → Prices.`;
}
