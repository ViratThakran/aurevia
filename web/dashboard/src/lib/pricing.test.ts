import { describe, expect, it } from "vitest";

import { describeUnpriced, unpricedWarning } from "./pricing";

const items = [
  { resource: "llm_output_tokens", unpriced_quantity: "500000" },
  { resource: "tts_characters", unpriced_quantity: "0" },
  { resource: "stt_seconds", unpriced_quantity: "12.5" },
];

describe("unpriced usage", () => {
  it("lists each unpriced amount with its label, skipping zeros", () => {
    expect(describeUnpriced(items, { llm_output_tokens: "AI model: output tokens" })).toBe(
      "5,00,000 AI model: output tokens; 12.5 stt_seconds",
    );
  });

  it("gives no warning when everything is priced", () => {
    expect(unpricedWarning([])).toBeNull();
    expect(unpricedWarning(undefined)).toBeNull();
    expect(unpricedWarning([{ resource: "x", unpriced_quantity: "0" }])).toBeNull();
  });

  it("says the spend limit is understated only when there is one", () => {
    expect(unpricedWarning(items, { spendLimit: true })).toContain("counts as zero toward the monthly spend limit");
    expect(unpricedWarning(items)).toContain("The cost shown leaves it out.");
    expect(unpricedWarning(items)).not.toContain("spend limit");
  });
});
