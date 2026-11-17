# Audit Trail

A simplified, human-readable ledger of every spec change, code change, and bug fix.
Governed by `.qoder/rules/spec-driven-development.md`.

## How to read

- **ID** — sequential `A-<n>`.
- **Type** — `SPEC` (spec created/updated), `CODE` (feature/enhancement), `BUG-CODE` (code deviated from spec → fixed), `BUG-SPEC` (spec itself wrong/ambiguous → needs user decision), `PROCESS` (workflow/tooling).
- **Spec refs** — affected requirement IDs from `SPEC.md` (`GAP-*` = open spec question).
- **Status** — `done` / `open` / `consulting` (waiting on user decision).

## Log

| ID | Date | Type | Summary | Spec refs | Status |
| --- | --- | --- | --- | --- | --- |
| A-000 | 2026-11-03 | SPEC | Compiled baseline `SPEC.md` v1.0 from code + `docs/*.md`; 8 open GAPs raised for user decision | all | done |
| A-001 | 2026-11-02 | CODE | Broker migration: Angel One SmartAPI → Upstox feed v3 (new `upstox_streamer.py`, config env swap, mock seeds + frontend map re-keyed, requirements swap, `angel_one_streamer.py` deleted). Retro-logged at spec baseline; compile + 10 dependency-free tests verified | SPEC-CFG-2/5, SPEC-S-3, SPEC-MKT-3/4/5/6, SPEC-NF-5 | done |
| A-002 | 2026-11-03 | PROCESS | Adopted spec-driven development; added `.qoder/rules/spec-driven-development.md` (spec-first, bug classification, audit logging) | — | done |
| A-003 | 2026-11-17 | SPEC | Spec v1.1: recorded decisions GAP-1b, GAP-3b, GAP-5b, GAP-6a, GAP-8b; rewrote SPEC-PER-5, SPEC-API-1/8, SPEC-MDL-6, SPEC-MKT-2, SPEC-NF-4; GAP-2/4/7 left open | SPEC-PER-5, SPEC-API-1/8, SPEC-MDL-6, SPEC-MKT-2, SPEC-NF-4 | done |
| A-004 | 2026-11-17 | CODE | GAP-1b: explicit `null` now clears optional trade fields (both repositories stop filtering `None`); `TradeResponse` rebuilt without input validators to avoid double-escaping on read; `state.js` converts emptied numeric inputs to `null` before PUT | SPEC-PER-5, SPEC-MDL-6 | done |
| A-005 | 2026-11-17 | CODE | GAP-3b: removed legacy query-param compat routes from `journal.py`; `/api/journal` is `GET`-only and the old verbs return 405 | SPEC-API-8 | done |
| A-006 | 2026-11-17 | CODE | GAP-5b: `PriceCache` stores `(ltp, timestamp)`, adds `get_batch_meta`, `PRICE_MAX_AGE_SECONDS` (default 30); `/api/prices` now returns `meta.as_of/stale`; values are flagged, never dropped | SPEC-MKT-2, SPEC-API-1, SPEC-CFG-2 | done |
| A-007 | 2026-11-17 | CODE | GAP-8b: added `app/models/responses.py` (`DataResponse[T]`, `MessageResponse`, `PricesResponse`, `JournalResponse`) and wired `response_model` on every route — OpenAPI is now typed | SPEC-API-0, SPEC-MDL-6 | done |
| A-008 | 2026-11-17 | PROCESS | Test harness: `pytest.ini` with `asyncio_mode = auto`; new `test_market_data.py`; extended cache/repo/API tests. Full suite: 33 passed (after `pip install motor pytest-asyncio`) | SPEC-NF-4 | done |
| A-009 | 2026-11-17 | CODE | Docs refresh: `file_by_file_design_reference.md`, `design_decisions_and_tradeoffs.md`, `codebase_knowledge.md` updated for Upstox (no Angel One/TOTP left), removed compat routes, staleness meta, response models | SPEC-MKT-3, SPEC-API-1/8, SPEC-NF-4 | done |
| A-010 | 2026-11-18 | DOCS | `architecture.md` diagrams repaired and verified with mermaid-cli (6/6 render): quoted subgraph/node labels (unquoted `(...)` caused `got 'PS'` parse error), replaced the class-diagram implementation arrow (not valid in flowcharts) with a dotted `-.->` link, moved the dashboard into its own `Browser Dashboard` frame so the container no longer encloses it, and corrected the stale Paise-conversion / numeric-token steps in 2.1 to Upstox feed v3 `ltpc` semantics | SPEC-MKT-3, SPEC-API-1 | done |
| A-011 | 2026-11-18 | SPEC | Spec v1.3: (1) credential model corrected to the Upstox **Analytics Access Token** (1-year, read-only, Market Data + Streaming) — GAP-7 closed, no OAuth app or daily refresh; (2) decision recorded for a public site with open signup: Clerk identity + owner-scoped data on the existing Atlas cluster (option A), deployment unchanged (Vercel + Render); (3) new §10 adds SPEC-AUTH-1..13, SPEC-FE-10/11, SPEC-NF-6, SPEC-API-10 (`/health`), CFG-2 rows for `ENV` / `CLERK_ISSUER` / `AUTH_DISABLED`; (4) GAP-6 re-decided to (b) per-owner unique index; (5) GAP-9 (watchlist), GAP-10 (abuse limits), GAP-11 (legacy claim) raised. Facts corrected in `config.py`, `upstox_streamer.py`, `codebase_knowledge.md`, `design_decisions_and_tradeoffs.md`, `file_by_file_design_reference.md`, `production_deployment_guide.md` | SPEC-CFG-2, SPEC-MKT-3, SPEC-AUTH-1..13, SPEC-FE-10/11, SPEC-NF-6, SPEC-API-10 | done |
