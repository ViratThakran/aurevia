import { describe, expect, it } from "vitest";

import { describeLabel, labelValue } from "./labels";

describe("label values", () => {
  it("builds the value shape the API expects", () => {
    expect(labelValue("objection", "price")).toEqual({ category: "price" });
    expect(labelValue("talk_ratio", "0.4")).toEqual({ expert_share: 0.4 });
    expect(labelValue("qualification", "budget", " about 5 lakh ")).toEqual({
      fact: "budget",
      note: "about 5 lakh",
    });
    expect(labelValue("stage", "pitch", "ignored")).toEqual({ stage: "pitch" });
  });

  it("describes stored labels", () => {
    expect(describeLabel("next_step", { step: "call_back" })).toBe("Next step: call back");
    expect(describeLabel("unknown", {})).toBe("unknown");
  });
});
