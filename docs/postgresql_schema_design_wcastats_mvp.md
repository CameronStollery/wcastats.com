The below was written by ChatGPT and has not been yet modified.

# PostgreSQL Schema Design for WCA Stats MVP

This schema is designed for:
- PostgreSQL on Amazon RDS
- FastAPI backend
- future analytics + query history
- low operational complexity
- easy future scaling

The current core tables are:
- `users`
- `queries`
- `query_runs`

The design assumes:
- users can save queries
- queries can be run many times
- query executions are tracked separately
- future async/background execution support
- possible future billing/rate limiting

---

# General Design Conventions

## Naming

Use:
- lowercase
- snake_case
- plural table names

Example:

```sql
query_runs
created_at
user_id
```

---

# ID Strategy

## Recommendation: UUID primary keys

Use:

```sql
UUID
```

instead of:
- SERIAL
- BIGSERIAL
- auto-increment integers

Reasons:
- safer for public APIs
- avoids ID enumeration
- better for distributed systems
- easier future migrations
- easier event-driven architecture later
- avoids exposing internal scale

PostgreSQL handles UUIDs very well.

---

# UUID Generation

## Recommended extension

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Then:

```sql
DEFAULT gen_random_uuid()
```

This is the modern PostgreSQL recommendation.

Avoid:
- uuid-ossp unless specifically needed

---

# Timestamp Strategy

Use:

```sql
TIMESTAMPTZ
```

for all timestamps.

Reasons:
- timezone-safe
- UTC-friendly
- avoids future bugs
- standard modern practice

Always store timestamps in UTC.

---

# Enum Strategy

Avoid PostgreSQL ENUM types initially.

Use:
- TEXT + CHECK constraints

Reasons:
- easier migrations
- easier deployment
- easier future modifications
- avoids enum migration pain

---

# Users Table

## Purpose

Stores:
- authentication/account data
- ownership of saved queries
- future preferences/subscriptions

---

## Schema

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,

    password_hash TEXT,

    auth_provider TEXT NOT NULL DEFAULT 'local'
        CHECK (auth_provider IN ('local', 'google', 'github')),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,

    last_login_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Notes

### email

Use TEXT instead of VARCHAR.

PostgreSQL stores them identically internally.

Add validation at the application layer.

---

### username

Keep usernames immutable if possible.

Changing usernames later creates surprising complexity.

---

### password_hash

Nullable because:
- OAuth users may not have local passwords

Never store passwords directly.

Use:
- Argon2id preferred
- bcrypt acceptable

---

### auth_provider

Supports future OAuth expansion.

---

# Recommended User Indexes

```sql
CREATE INDEX idx_users_created_at
    ON users(created_at);

CREATE INDEX idx_users_last_login_at
    ON users(last_login_at);
```

---

# Queries Table

## Purpose

Stores saved user queries.

A query represents:
- a saved search
- leaderboard configuration
- ranking request
- analytics definition
- custom filter

This table stores the query definition itself.

Execution history goes into `query_runs`.

---

# Recommended Query Storage Strategy

Store query definitions as:

```sql
JSONB
```

NOT raw SQL.

Reasons:
- safer
- easier validation
- easier versioning
- API-friendly
- future frontend compatibility

Example query definition:

```json
{
  "event": "333",
  "region": "Australia",
  "metric": "average",
  "top_n": 100
}
```

---

# Queries Schema

```sql
CREATE TABLE queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,

    name TEXT NOT NULL,

    description TEXT,

    query_definition JSONB NOT NULL,

    is_public BOOLEAN NOT NULL DEFAULT FALSE,

    query_version INTEGER NOT NULL DEFAULT 1,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

# Recommended Query Indexes

```sql
CREATE INDEX idx_queries_user_id
    ON queries(user_id);

CREATE INDEX idx_queries_created_at
    ON queries(created_at DESC);

CREATE INDEX idx_queries_is_public
    ON queries(is_public);
```

---

# JSONB Index

This becomes valuable later if filtering heavily on query contents.

```sql
CREATE INDEX idx_queries_definition_gin
    ON queries
    USING GIN(query_definition);
```

Do not over-index JSONB initially unless needed.

---

# Query Runs Table

## Purpose

Tracks every execution of a query.

This table is extremely important operationally.

It enables:
- debugging
- performance tracking
- usage analytics
- async execution
- caching
- audit history
- future billing/rate limiting
- failure tracking

---

# Query Run Status Model

Use:

```text
pending
running
completed
failed
cancelled
```

Stored as TEXT + CHECK.

---

# Query Results Strategy

Do NOT store large result sets directly in PostgreSQL initially.

Instead:
- store results in S3/parquet/cache later
- keep metadata in Postgres

Postgres should track:
- execution metadata
- performance
- references to stored results

not huge analytical datasets.

---

# Query Runs Schema

```sql
CREATE TABLE query_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    query_id UUID NOT NULL
        REFERENCES queries(id)
        ON DELETE CASCADE,

    user_id UUID
        REFERENCES users(id)
        ON DELETE SET NULL,

    status TEXT NOT NULL
        CHECK (status IN (
            'pending',
            'running',
            'completed',
            'failed',
            'cancelled'
        )),

    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    duration_ms INTEGER,

    row_count INTEGER,

    error_message TEXT,

    execution_metadata JSONB,

    result_location TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

# Notes on Query Runs Fields

## duration_ms

Use INTEGER.

Milliseconds are sufficient.

INTEGER supports up to:
- ~24 days

which is more than enough.

---

## result_location

Potential future values:

```text
s3://bucket/results/abc.parquet
redis:key
cache:xyz
```

---

## execution_metadata

Example:

```json
{
  "engine": "athena",
  "cache_hit": true,
  "athena_query_id": "abc123"
}
```

---

# Recommended Query Run Indexes

## Critical indexes

```sql
CREATE INDEX idx_query_runs_query_id
    ON query_runs(query_id);

CREATE INDEX idx_query_runs_user_id
    ON query_runs(user_id);

CREATE INDEX idx_query_runs_status
    ON query_runs(status);

CREATE INDEX idx_query_runs_created_at
    ON query_runs(created_at DESC);
```

---

# Very Important Composite Index

This will likely become your most-used operational query:

```sql
CREATE INDEX idx_query_runs_query_created
    ON query_runs(query_id, created_at DESC);
```

---

# Optional Future Tables

Likely additions later:

```text
api_keys
sessions
saved_results
cached_rankings
query_favorites
organizations
teams
subscriptions
rate_limits
background_jobs
```

---

# Recommended Updated Timestamp Trigger

Instead of manually updating `updated_at`, use a trigger.

---

## Trigger Function

```sql
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Users Trigger

```sql
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
```

---

## Queries Trigger

```sql
CREATE TRIGGER trg_queries_updated_at
BEFORE UPDATE ON queries
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
```

---

# Recommended Future Partitioning Strategy

Do NOT partition initially.

Later, if `query_runs` becomes very large:
- partition by month on `created_at`

But premature partitioning adds operational complexity.

---

# Recommended Migration Tooling

Use:

- Alembic
- SQLAlchemy 2.x

with FastAPI.

---

# Recommended SQLAlchemy Mapping Strategy

Use:
- SQLAlchemy ORM models
- Pydantic schemas separately

Avoid:
- mixing ORM and API models directly

---

# Final Recommended Architecture

## PostgreSQL stores

- users
- metadata
- query definitions
- query execution history
- API-serving tables
- rankings/cache metadata

## S3/Athena stores

- large analytical outputs
- parquet datasets
- historical exports
- heavy scans

This separation will scale much better than pushing analytics into PostgreSQL.

---

# Final Recommendation Summary

| Decision | Recommendation |
|---|---|
| Primary keys | UUID |
| UUID generation | gen_random_uuid() |
| Timestamps | TIMESTAMPTZ |
| Table naming | plural snake_case |
| Query definitions | JSONB |
| Large results | store outside Postgres |
| Enums | TEXT + CHECK |
| Password storage | Argon2id hashes |
| Index strategy | minimal but intentional |
| Partitioning | not initially |
| Migration tooling | Alembic |
| ORM | SQLAlchemy 2.x |

