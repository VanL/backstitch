# Agent Inventory

## Purpose and Scope

This document records which agent families are currently available in the
environment and which ones are preferred for independent review work.

Keep it lightweight and refresh it when tooling changes materially.

## Governing Spec References

- `docs/specs/01-development-documentation-operating-model.md` [DOM-3]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-11]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-13]

## Verification Method

To refresh this inventory:

1. run a small read-only review or no-op prompt against each available agent
   interface
2. record whether it is:
   - verified usable
   - present but blocked by credentials or configuration
   - present but currently failing at invocation time
3. update the refresh date and notes

## Current Observed Availability

Last refreshed: not yet refreshed in this repository

| Agent family | Status | Notes |
|--------------|--------|-------|
| Claude | not yet checked | |
| Codex | not yet checked | |
| Gemini | not yet checked | |
| Qwen | not yet checked | |
| Kimi | not yet checked | |

## Review Preference

For plan review and final review:

1. prefer a different agent family than the authoring agent
2. if several are available, prefer one that has not already shaped the plan
3. if only one family is available, note that limitation and do a stricter
   fresh-eyes review

## Refresh Guidance

Update this file when:

- the available tool surface changes
- a new agent family becomes available
- an existing agent family is removed
- review workflow preferences change materially
