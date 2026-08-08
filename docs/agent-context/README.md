# Agent Context Hub

This folder is the canonical shared context for coding agents, automation
agents, and human contributors working in this repository.

## Goals

- Keep one repo-owned source of truth for durable execution standards.
- Reduce drift across agent-specific root files.
- Make planning, testing, and documentation maintenance explicit.
- Make review loops, agent bootstrap, and skill maintenance explicit.
- Keep spec, plan, implementation, and code traceability bidirectional.

## Read Order

Start with the conceptual account, then process. This list, root
`AGENTS.md`, and `context.index.yaml` `read_order` name the same
sequence element-for-element.

1. `../program-theory.md` — conceptual identity of **this repository**
   (what kind of system this is; frames placement and refusal). Program
   theory does not override winning contracts. If Status is `Stub`, begin
   crystallization before committing product-scope behavior; exploration
   may proceed. Extend local depth with **module theory** on entry, not by
   bulking this file.
2. This file — `README.md` (the hub overview you are reading).
3. `decision-hierarchy.md`
4. `principles.md`
5. `engineering-principles.md`
6. Relevant runbook(s) in `runbooks/`
7. `lessons.md`
8. `../lessons.md` — required startup reading is the **Golden Rules section
   plus dated entries after the lessons watermark** (see `../coalescing.md`).
   Older entries are searchable reference material, not startup context.

Machine-readable order: `context.index.yaml` `read_order`.

Read-order compliance is a declared-claim floor, not a gate: when you produce
product-scope judgment — a plan, review, audit, or design opinion — declare
which of these surfaces you consulted. Plans do this via their
source-documents section; plan-free work declares it in its report. The
declaration is checked by review, like task classification ([DOM-15]), not
by tooling.

## Runbooks

- `writing-plans.md`: how to write executable implementation plans (including
  spec baseline, proposed spec delta, promotion slices, and status rungs)
- `hardening-plans.md`: required companion for risky or boundary-crossing plans
  that must survive review
- `review-loops-and-agent-bootstrap.md`: how to bootstrap available agents and
  run independent plan/work reviews
- `writing-specs.md`: how to define intended behavior with stable references
- `writing-implementation-docs.md`: how to capture rationale and boundaries
- `testing-patterns.md`: how to choose the right proof and avoid weak tests
- `adversarial-acceptance-probes.md`: the black-box probe kit any
  implementation must pass before integration, independent of spec version
- `designing-agent-facing-interfaces.md`: principles for designing any
  surface an agent consumes — APIs, CLIs, and structured documentation
  (adopted from agent-guidance; directly relevant to the backstitch CLI)
- `maintaining-traceability.md`: how to keep docs synchronized during delivery
- `skills-lifecycle.md`: how to add, update, and retire reusable skills
- `external-skill-suites.md`: precedence and crosswalk for external skill
  suites (superpowers, gstack, Every's compound engineering)

## What Belongs Here

- durable decision policies
- reusable engineering workflow guidance
- short pointers into the canonical lessons ledger

## What Does Not Belong Here

- product or architecture specs that define the system itself
- one-off execution notes for a single task
- agent-vendor-specific syntax that is not reusable across tools

## Maintenance Rules

- Keep files short, operational, and repository-owned.
- Prefer checklists and direct rules over long prose.
- When a repeated mistake shows up, add a lesson in `../lessons.md` and
  strengthen a runbook if the fix should become reusable guidance.
- When plans keep failing at boundaries, strengthen `writing-plans.md` or
  `runbooks/hardening-plans.md` instead of leaving the correction trapped in a
  single plan.
- When a repeated workflow becomes stable and reusable, promote it into a skill
  under `../skills/`.
