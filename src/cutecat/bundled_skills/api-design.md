# API design

Use when designing or reviewing an HTTP API, a public interface, or a library's
surface — anything other people will call and you can't easily change later.

**An API is a promise.** You can add to it freely; you can almost never take
away. Design for the thing you'll be stuck with.

## HTTP shape

- **Nouns for resources, verbs from HTTP.** `POST /orders`, `GET /orders/42`,
  not `POST /createOrder`.
- **Status codes that mean what they say**: `200` ok, `201` created (with a
  `Location`), `400` your fault, `401` who are you, `403` not allowed, `404`
  gone or never was, `409` conflict, `422` well-formed but wrong, `429` slow
  down, `5xx` our fault. Never `200 {"error": …}`.
- **Errors are structured and stable**, with a machine-readable code and a human
  message: `{"error": {"code": "insufficient_funds", "message": "…"}}`. Clients
  match on the code, never on the prose.
- **Paginate every list**, from day one. A cursor beats an offset (stable under
  writes). Never return an unbounded array.
- **Idempotency for writes** that a client might retry: an `Idempotency-Key` on
  `POST`, or make the operation a `PUT` on a client-chosen id.
- **Version at the edge** (`/v1/…`) and treat it as expensive. Prefer additive
  changes.

## Compatibility rules

Safe: adding an endpoint, adding an optional field, adding an enum value the
client already tolerates.

Breaking (needs a version, or a migration and a deprecation window): removing or
renaming a field, tightening validation, changing a type, changing a default,
changing a status code, making an optional field required.

**Note:** adding an enum value *is* breaking for a client that switches
exhaustively on it. Say so.

## Rules

- **Design the error cases first.** They are most of the real surface, and
  they're what people integrate against at 3am.
- **Return the resource you just changed.** It saves the caller a round trip.
- **Never leak internals**: no stack traces, no SQL, no internal ids in errors.
- **Write the client call before you write the server.** If the call is awkward
  to write, the API is wrong — that's the cheapest test you'll ever run.
