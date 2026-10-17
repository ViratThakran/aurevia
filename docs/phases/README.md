# Phases 10 to 18

One file per phase of the master plan (`docs/plan/aurevia-master-plan.pdf`, 15 Oct 2026). The
plan is the source of truth; these files track progress against it. Current state is in
`docs/STATUS.md`.

**Current phase: [Phase 10](phase-10.md).** Do not start a later phase early (plan rule 10).

| Phase | Name | Gate | State |
|---|---|---|---|
| [10](phase-10.md) | Speed and voice acceptance | G10 | In progress |
| [11](phase-11.md) | Human feel | G11 | Not started |
| [12](phase-12.md) | Learning from the expert recordings | G12 | Not started |
| [13](phase-13.md) | Make it cheap | G13 | Not started |
| [14](phase-14.md) | Phone go-live | G14 | Not started |
| [15](phase-15.md) | Integrations that replace the sales workflow | G15 | Not started |
| [16](phase-16.md) | A product companies can buy | G16 | Not started |
| [17](phase-17.md) | Pilots and launch | G17 | Not started |
| [18](phase-18.md) | Later, after Gate 17 | none (triggers) | Not started |

The plan runs four tracks side by side that meet at the pilots. Phase 12's timing profile feeds
Phase 11, Phase 13's carrier quote feeds Phase 14, and Phase 17 starts when each track has
reached its last gate. Which phases sit on which track is shown only in the plan's roadmap
diagram: **to confirm**.

## How to use these files

- Every phase file has the same sections: goal; gate and how to measure it; work packages
  with status and PR; decisions and open questions; parts of the system it touches; risks and
  dependencies; measured results; done checklist.
- **Measured results hold real numbers only.** Mark each one as mocked, real provider,
  synthetic audio or human call. Never copy an estimate into that section as a result.
- Anything the plan does not state clearly is marked **to confirm**.
- Update the phase file in the same PR as the work, and `docs/STATUS.md` at the end of every
  session. One work package per PR (plan rule 1).
- Work package status values: Not started, In progress, In review (PR open), Done (merged and
  its done-when met), Blocked.
