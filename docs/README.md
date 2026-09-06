# Documentation — Offline AI Assistant Redesign

This folder is the **single source of truth** for the redesign plan and progress. It is updated after every successfully completed step.

## Contents

| Document | Purpose | When it is updated |
|---|---|---|
| [`project_plan.md`](project_plan.md) | **PLAN** — map of all steps (9 phases, 47 steps), dependencies, verification criteria | Rarely (only when the plan structure changes) |
| [`current_status.md`](current_status.md) | **STATUS** — progress tracking per step, change log, open issues | **After every successfully completed step** |
| [`design_system.md`](design_system.md) | Complete specification of the target design (palettes, components, layout) from `Izgled Aplikaccije/` | When the design is changed |
| [`models_report.md`](models_report.md) | Analysis of candidates from E:\models, model decisions, paths, inference parameters | When the model selection changes |
| [`environment.md`](environment.md) | Hardware, Python environments (3.11 verified), standard commands, runtime paths | When the environment changes |
| [`qa_checklist.md`](qa_checklist.md) | Definition of "no regression" — smoke suite, functional matrix F1–F20, visual checks | Stable |

## How to work (workflow)

1. Read `project_plan.md` — find the first unfinished step (in phase order).
2. Execute the step.
3. Verify according to the "Verification" column in the plan + relevant items from `qa_checklist.md`.
4. Update `current_status.md`: change the step status (⬜→✅), the phase percentage, and add a row to the "Change log".
5. Commit.

## Brief status summary (2026-09-04)

- Analysis completed; the launcher contains a confirmed `NameError` bug (fix in step 1.1)
- Models selected and **copied into the project**: Qwen2.5-Coder-7B Q4_K_M (primary) + Phi-4-mini Q6_K_L (secondary)
- Development on **Python 3.11.9** (llama-cpp-python unavailable on 3.14)
- Next step: **0.1 Git init** → **0.3 Baseline test suite** → PHASE 1
