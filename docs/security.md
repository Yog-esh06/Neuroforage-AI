# Security

## Authentication and authorization

* **JWT bearer tokens** (HS256, `JWT_SECRET`, `JWT_EXPIRE_MINUTES`), passwords hashed with bcrypt. Login failures return one
  uniform message (no user enumeration) and are audited.
* **Roles** (`core/security.py`): `viewer < analyst < reviewer < admin`, enforced per endpoint with `require_role`:

| Capability | Minimum role |
|---|---|
| Read documents, search, knowledge, insights, dashboard | viewer |
| Upload, ask (generate answers), compare, re-analyse | analyst |
| Review decisions, workflow CRUD, delete documents, resolve contradictions, read the audit trail | reviewer |
| Create users | admin |

* `AUTH_ENABLED=false` (demos/tests only) serves an anonymous admin; production start-up **refuses** to boot with
  `AUTH_ENABLED=false`, the default JWT secret, or the default seed admin password (`APP_ENV=production`).

## Upload and file handling

Extension allow-list + magic-byte sniffing (content must match the extension), bounded reads and `MAX_UPLOAD_MB`, page
limit, sanitised names, generated storage keys, storage root confinement, `X-Content-Type-Options: nosniff` and
`Content-Disposition: attachment` on downloads. PDFs are parsed by PyMuPDF and images by OpenCV in the worker process; for
hostile-file threat models run workers in a sandboxed container (see *Known limitations*).

## API hardening

Pydantic validation on every body/query parameter (bounds on lengths, `k`, hops, weights, enumerated values), structured
error envelope, no stack traces in responses, parameterised SQL through SQLAlchemy only, CORS restricted to
`CORS_ORIGINS` with explicit methods/headers, security headers (`X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`).

## Secrets and logging

All secrets come from the environment (`.env` is git-ignored; `.env.example` documents every variable). The LLM key is read
server-side only and never serialised into any response, the dashboard, health check or frontend bundle (a test asserts
this). The root logger installs a redacting filter (`api_key`, `password`, `token`, `Authorization: Bearer …`, `sk-…`), and
audit `query_text`/`summary` are redacted before hashing.

## Audit integrity

`audit_logs` is append-only and hash-chained (`hash = SHA-256(record body ‖ prev_hash)`). `GET /audit/verify` recomputes the
chain and reports the first altered or missing record; a test tampers with a row and asserts detection. The chain detects
modification by anyone without recomputing every later hash; it does not prevent a database administrator from rewriting the
whole chain — export hashes to an external system (WORM storage, a ledger) if that threat is in scope.

## Known limitations

* The JWT is stored in `localStorage` by the SPA (simple, but exposed to XSS). A production deployment should move to
  httpOnly cookies behind a same-origin proxy (the provided nginx profile supports this) and add CSRF protection.
* No rate limiting, account lockout or MFA are implemented; put the API behind a gateway/WAF for internet exposure.
* Document-level ACLs are not implemented: every authenticated user sees every document in the workspace (roles gate
  actions, not rows).
* Uploaded documents are sent to a third-party LLM **only** if you configure a remote provider; the default provider is local.
