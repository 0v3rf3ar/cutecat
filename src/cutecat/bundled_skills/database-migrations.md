# Database migrations

Use when changing a database schema, or when a change involves data already in
production. This is the class of change you cannot undo with `git revert`.

**The old code and the new schema must be able to coexist.** Deploys are not
atomic: for some window, both versions run against the same database. Every rule
below follows from that.

## The expand / migrate / contract pattern

Never rename or drop in one step. Three deploys:

```
1. EXPAND    add the new column (nullable, or with a default). Write to BOTH
             old and new. Deploy. Nothing reads the new one yet.
2. MIGRATE   backfill the existing rows, in batches. Verify. Switch reads to
             the new column. Deploy.
3. CONTRACT  stop writing the old column. Deploy. Only then drop it — days
             later, once you're sure you won't roll back.
```

A rename is an expand + a backfill + a contract. So is a type change. So is
splitting a column in two.

## Rules

- **Every migration is reversible, or says loudly that it isn't.** Write the
  `down` and test it, before you run the `up`.
- **Never destroy data in a migration you can't undo.** A `DROP COLUMN` in the
  same deploy as the code that stopped using it means a rollback loses data.
- **Backfill in batches**, with a `WHERE` on an indexed column and a sleep
  between batches. A single `UPDATE` over ten million rows locks the table and
  takes the site down.
- **Adding an index takes a lock.** Use `CREATE INDEX CONCURRENTLY` (Postgres) or
  the equivalent, and never inside a transaction.
- **Adding a `NOT NULL` column with a default rewrites the table** on older
  engines. Add it nullable, backfill, then add the constraint.
- **Test the migration against a copy of real data**, not an empty dev database.
  Nulls, duplicates and the row that was inserted in 2015 by a script nobody
  remembers are what break it.

## Before you run it

```
- [ ] the `down` exists and was tested
- [ ] a backup exists, and you know how long a restore takes
- [ ] the old code still works against the new schema
- [ ] the batch size and the lock behaviour are understood
```
