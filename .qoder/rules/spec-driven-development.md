# Spec-Driven Development Rule

`SPEC.md` is the single source of truth for this repository's behavior. `AUDIT.md` is the change ledger. `docs/*.md` and `docs/codebase_knowledge.md` are narrative context, never normative.

## Before any code change

1. Identify the affected requirement IDs in `SPEC.md` (e.g. SPEC-PER-5) or state that a new requirement is needed.
2. If the intended change contradicts `SPEC.md`, update `SPEC.md` FIRST (bump its version, state the new requirement), then change the code. Never the other way around.
3. If the change touches an open question in `SPEC.md` §10 (GAP-*), stop. GAPs are user decisions: present the options and wait.

## Bug classification (mandatory for every bug found)

- **Code bug** — the code deviates from `SPEC.md`. Fix it directly, run the relevant checks/tests, and log it in `AUDIT.md` as `BUG-CODE`. No permission needed.
- **Critical code bug** — data loss/corruption, security vulnerability, or wrong money/P&L numbers: report to the user BEFORE fixing, even though it is a code bug.
- **Spec bug** — `SPEC.md` itself is wrong, ambiguous, incomplete, or the desired behavior is in question. Do NOT change code. Propose the spec amendment (ID, current wording, proposed wording, impact) and log it as `BUG-SPEC` with status `consulting`. Only the user resolves it.

## Audit trail (mandatory)

Append one row to `AUDIT.md` for every: spec change, code change, bug fix, or new GAP. Use the existing format (sequential `A-<n>`, ISO date, type, one-line summary, spec refs, status). Keep summaries to one line; details belong in the code/spec itself.

## Conventions to preserve while implementing

- Endpoints stay thin; response envelope `{"success", "data"|"message"}`; `HTTPException(400|404)`.
- Layering: endpoints → service → repository interface → mongo/memory implementation.
- All data-path code is `async`; `PriceCache` stays sync with `threading.Lock`.
- Frontend: local-first state + fire-and-forget backend sync; `escapeHtml` on user text; camelCase wire fields.
