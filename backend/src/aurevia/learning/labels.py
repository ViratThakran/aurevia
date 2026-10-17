"""Label values by kind (WP-12.4). The model proposes labels later; a person checks them.

Each kind has a fixed value shape, so labels stay comparable across calls and a model's
proposals can be scored against a person's check (label accuracy).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aurevia.learning.models import LabelKind, ReviewStatus

Stage = Literal[
    "opening", "discovery", "qualification", "pitch", "objection", "next_step", "follow_up"
]


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StageValue(_Value):
    stage: Stage


class ObjectionValue(_Value):
    category: Literal["price", "timing", "authority", "need", "other"]


class OutcomeValue(_Value):
    result: Literal["qualified", "disqualified", "educate", "realign"]


class QualificationValue(_Value):
    fact: Literal["budget", "authority", "need", "timeline"]
    note: str = Field(default="", max_length=200)


class NextStepValue(_Value):
    step: Literal["meeting", "call_back", "stay_in_touch", "referral", "email", "none"]


class TalkRatioValue(_Value):
    expert_share: float = Field(ge=0, le=1)


class QuestionCountValue(_Value):
    count: int = Field(ge=0, le=1000)


VALUE_SHAPES: dict[LabelKind, type[_Value]] = {
    LabelKind.STAGE: StageValue,
    LabelKind.OBJECTION: ObjectionValue,
    LabelKind.OUTCOME: OutcomeValue,
    LabelKind.QUALIFICATION: QualificationValue,
    LabelKind.NEXT_STEP: NextStepValue,
    LabelKind.TALK_RATIO: TalkRatioValue,
    LabelKind.QUESTION_COUNT: QuestionCountValue,
}
# Where a label sits: on a line (where the stage starts, where an objection is raised), on the
# whole call, or either.
ON_A_LINE = frozenset({LabelKind.STAGE, LabelKind.OBJECTION})
WHOLE_CALL = frozenset(
    {LabelKind.OUTCOME, LabelKind.NEXT_STEP, LabelKind.TALK_RATIO, LabelKind.QUESTION_COUNT}
)


class LabelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LabelKind
    line_seq: int | None = Field(default=None, ge=0)
    value: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> LabelIn:
        self.value = VALUE_SHAPES[self.kind].model_validate(self.value).model_dump()
        if self.kind in ON_A_LINE and self.line_seq is None:
            raise ValueError(f"a {self.kind.value} label needs the line it starts on")
        if self.kind in WHOLE_CALL and self.line_seq is not None:
            raise ValueError(f"a {self.kind.value} label is for the whole call, not a line")
        return self


class LabelReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[ReviewStatus.APPROVED, ReviewStatus.REJECTED]
