# QueryPerf AI — Next-Gen SQL Optimization Platform

> Automated SQL optimizer, anti-pattern linter, and empirical benchmarking engine for SQLite, PostgreSQL, and MySQL queries.

QueryPerf AI has been upgraded with 12 advanced capabilities, eliminating any static or mock numbers in favor of 100% empirical database measurements, and styled with an elite dark-tech aesthetic. It creates an isolated database for every analysis, fills it with deterministic synthetic data, obtains execution plans, requests structured recommendations from a local Ollama model (or deterministic fallback), applies safe index recommendations, and benchmarks both versions of the query.

The application is designed to be useful even without a running LLM: its built-in deterministic linter still detects 18+ common SQL smells and produces a conservative optimization where possible.

## 1. Introduction

### 1.1 Purpose

The purpose of this Software Requirements Specification (SRS) and project documentation is to describe the architecture, behavior, interfaces, constraints, and operation of QueryPerf AI.

QueryPerf AI addresses a common problem in database development: a developer may know that a query is slow but may not know whether the root cause is a table scan, a non-SARGable predicate, unnecessary data retrieval, a missing join index, or a combination of these factors. Rather than only generating an AI recommendation, the project tests that recommendation against a newly seeded sandbox and presents empirical timing data.

The system has four primary goals:

1. Detect common SQL anti-patterns and plan-level bottlenecks.
2. Generate an optimized, read-only version of a submitted query and safe SQLite index recommendations.
3. Measure original and optimized query execution over the same deterministic synthetic dataset.
4. Present the result in a report suitable for academic demonstrations, discussion, or export.

### 1.2 Document Conventions

This document uses the following conventions:

| Convention | Meaning |
| --- | --- |
| `inline code` | File names, commands, configuration variables, SQL, API routes, and JSON fields. |
| **Bold text** | Important concepts, requirements, or cautions. |
| `GET /api/health` | An HTTP method followed by its route. |
| `:memory:` | A new, ephemeral SQLite database stored only in process memory. |
| `SELECT`, `WITH`, `EXPLAIN` | User query forms accepted by the sandbox. |

All SQL examples use SQLite-compatible syntax. Measured time is expressed in milliseconds (`ms`).

### 1.3 Intended Audience and Reading Suggestions

This document serves several audiences:

| Audience | Suggested sections |
| --- | --- |
| Project evaluator or instructor | Introduction, Product Scope, Architecture, Benchmarking Method, Security Model. |
| Developer setting up the project | Quick Start, Configuration, API Reference, Troubleshooting. |
| Database student or SQL learner | Core Concepts, Typical Findings, Sample Workflow. |
| Maintainer | Project Structure, Processing Pipeline, Known Constraints, Extension Ideas. |

For a quick demonstration, start with **Quick Start**, run the server, use **Load Sample Demo Data**, then submit the analysis. For an implementation review, read **System Architecture**, **Request Processing Pipeline**, and **Security Model**.

### 1.4 Product Scope

QueryPerf AI is a single-page web application with a Python/FastAPI backend and an in-memory SQLite benchmark sandbox. The user submits DDL and a read-only SQL query. The system then:

- validates the query and creates a fresh sandbox;
- creates the submitted schema and inserts approximately 1,200 deterministic records per compatible table;
- captures `EXPLAIN QUERY PLAN` output for the original query;
- asks Ollama for structured SQL analysis, or uses a local deterministic fallback;
- applies only valid, single `CREATE INDEX` recommendations;
- compares original and optimized execution plans;
- executes each query five times and reports average execution time; and
- renders a full-screen report with plan comparison, result preview, history, and JSON export.

The project is intentionally **not** a production database migration tool. It does not connect to a user's live database, retain their data on the server, execute user write statements, or guarantee that an LLM-generated optimization is appropriate for all database engines.

### 1.5 References

- [SQLite: EXPLAIN QUERY PLAN](https://www.sqlite.org/eqp.html)
- [SQLite: Query Planner](https://www.sqlite.org/queryplanner.html)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Pydantic documentation](https://docs.pydantic.dev/)
- [Ollama API documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)

## 2. Core Database Concepts

### SARGability

A predicate is **SARGable** (Search ARGument ABLE) when the database can use an index to locate matching values directly. For example:

```sql
-- Usually indexable when an index exists on order_date
WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'

-- Usually prevents normal index lookup on order_date
WHERE strftime('%Y', order_date) = '2025'
```

The latter must calculate `strftime` for candidate rows before comparing the result. The former gives the query planner a date range it can seek in a B-tree index.

### Full-table scans and B-tree indexes

A full-table scan visits every row in a table; its cost grows linearly with table size. A B-tree index can make selective lookup and join operations much faster, often approaching logarithmic lookup plus the cost of retrieving matches. Indexes consume additional storage and may slow writes, which is why the system reports a reason for each recommendation instead of blindly adding indexes.

### Anti-patterns detected

The built-in local linter now features an expanded scanner with **18+ deterministic rules**, including:

- `SELECT *` Column Projections
- `OR in WHERE` clause (defeats single index seek)
- `NOT IN (subquery)` NULL trap & unindexed scan
- `IN (subquery)` vs `EXISTS` semi-join
- Functions / Expressions on indexed columns (Non-SARGable `strftime`, `date`, `lower`, `substr`)
- Leading wildcard searches (`LIKE '%...'`)
- Unnecessary `DISTINCT`, `GROUP BY` without aggregate, `ORDER BY` without `LIMIT`
- Cartesian joins and missing `JOIN` predicates
- Redundant nested `SELECT` wrappers and subqueries

Ollama may identify additional issues, such as implicit casts or schema-specific refactoring, depending on the model used.

## 3. System Architecture

```text
┌───────────────────────────────────────────────────────────────────┐
│ Browser SPA (HTML, Tailwind CDN, Vanilla JavaScript)              │
│ DDL + query editor · report screen · export · local history       │
└───────────────────────────────┬───────────────────────────────────┘
                                │ POST /api/optimize
┌───────────────────────────────▼───────────────────────────────────┐
│ FastAPI application                                                │
│ Pydantic validation · CORS · structured HTTP errors               │
└───────────────┬──────────────────────────────────────┬────────────┘
                │                                      │
┌───────────────▼───────────────┐      ┌───────────────▼────────────┐
│ SQLite sandbox service         │      │ Ollama analysis service    │
│ fresh :memory: connection      │      │ strict JSON response       │
│ synthetic data seeding         │      │ local-linter fallback      │
│ plans + benchmark + preview    │      └────────────────────────────┘
└───────────────┬───────────────┘
                │
                ▼
      structured benchmark report returned to browser
```

### Request processing pipeline

1. The frontend sends `ddl_schema` and `slow_query` to `POST /api/optimize`.
2. Pydantic validates that both values are non-blank strings within the configured length limits.
3. The sandbox enforces the read-only query policy.
4. A new `sqlite3.connect(':memory:')` instance is created, the DDL is executed, and deterministic synthetic data is seeded.
5. SQLite captures the original execution plan.
6. Ollama receives the DDL, original query, and plan and returns JSON matching the analysis model. If this fails, the local linter provides a fallback analysis.
7. A second fresh sandbox recreates the same data, measures the original query five times, validates/applies index statements, captures the optimized plan, and measures the optimized query five times.
8. The API returns scores, findings, plans, timings, a five-row result preview, and report metadata.

## 4. Functional Features

QueryPerf AI features 12 advanced capabilities:

1. **Interactive Visual Execution Plan Tree**: Converts raw `EXPLAIN` output into a hierarchical tree of operations with a physical operator inspection drawer.
2. **SQL Anti-Pattern Scanner**: 18+ rules with severity, impact estimation, and one-click rewrite suggestions.
3. **Query Rewrite Playground**: Generates 3 intelligent refactoring candidates and dynamically flags the fastest version with a `🏆 BEST REWRITE` badge.
4. **Advanced Index Advisor**: Synthesizes and tests candidate indexes, computing a dynamic ⭐ 1-100 star rating based on whether scans were eliminated, outlining clear trade-offs.
5. **Benchmark Graphs & Distribution**: Visual resource comparison bars and a 25-iteration distribution histogram.
6. **Interactive What-If Index Simulator ("Index Lab")**: Allows typing any custom `CREATE INDEX ...` statement, simulates it in an isolated transaction, and reports the verdict.
7. **Query Complexity Analysis**: Evaluates overall Complexity Risk (`LOW`, `MEDIUM`, `HIGH`) and identifies dominant cost factors.
8. **Multi-Database Engine Selector**: Switch between **SQLite (Live Sandbox)**, **PostgreSQL**, and **MySQL**.
9. **Natural Language → SQL → Optimize Copilot**: Modal allowing English input, using local Ollama or heuristics to generate schema-aware SQL.
10. **Query Regression Detection**: Automatically detects if a query executes slower than its previous run in the historical ledger.
11. **Query Performance Analytics Dashboard**: Modal displaying aggregate KPIs computed directly from `.queryperf_history.sqlite`.
12. **Optimization Confidence Score (0–100)**: Objective scorecard verifying execution plan improvements, latency reduction, and read-only safety.

## 5. API Reference

FastAPI automatically exposes interactive API documentation at `http://127.0.0.1:8000/docs` while the server is running.

### `GET /api/health`

Returns a lightweight service-health response.

```json
{
  "status": "ok",
  "service": "QueryPerf AI"
}
```

### `POST /api/optimize`

Submits a schema and a read-only query for analysis.

#### Request body

```json
{
  "ddl_schema": "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);",
  "slow_query": "SELECT * FROM items WHERE name LIKE '%demo%';"
}
```

#### Successful response fields

| Field | Description |
| --- | --- |
| `health_score_original`, `health_score_optimized` | Integer query-health scores from 0 to 100. |
| `detected_anti_patterns` | Named SQL smells and descriptions. |
| `bottleneck_analysis` | Technical diagnosis of the original query. |
| `original_plan_summary` | Plain-language explanation of the original SQLite plan. |
| `optimized_query` | Proposed read-only SQL query. |
| `index_recommendations` | Safe `CREATE INDEX` statements and reasons. |
| `original_ms`, `optimized_ms` | Average time from five benchmark runs. |
| `speedup_factor` | Human-readable relative speed result. |
| `original_execution_plan`, `optimized_execution_plan` | Raw formatted SQLite plan output before and after indexes. |
| `optimized_preview` | Column names and up to five display-safe rows from the optimized result. |
| `analysis_engine` | Ollama model label or `Local deterministic linter`. |

#### Error responses

| Status | Meaning |
| --- | --- |
| `400 Bad Request` | Invalid DDL, invalid SQL, unsafe query, invalid AI-generated index statement, or SQLite execution error. |
| `422 Unprocessable Entity` | Request body does not satisfy Pydantic validation. |
| `500 Internal Server Error` | An unexpected failure that was caught and returned safely. |

Example unsafe-query error:

```json
{
  "detail": "The query contains a prohibited SQL operation. Only read-only SQL is allowed."
}
```

## 6. Security Model and Constraints

QueryPerf AI is a sandboxed demonstration tool, not a replacement for application authorization or production database access controls.

- **Fresh database per operation:** each sandbox uses a disposable `:memory:` SQLite database and is closed after the response.
- **Read-only input policy:** user queries must begin with `SELECT`, `WITH`, or `EXPLAIN`.
- **Blocked operations:** the validator rejects destructive or environment-changing operations including `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `PRAGMA`, `ATTACH`, `DETACH`, `VACUUM`, and `REPLACE`.
- **Single-statement policy:** embedded extra statements are rejected.
- **Time limit:** SQLite receives a three-second busy timeout and a progress handler interrupts long-running work.
- **Restricted model output:** only a single `CREATE INDEX` statement can be applied from a recommendation.
- **SQLite VM authorization:** file attachment, PRAGMAs, extension loading, triggers, views, virtual tables, destructive DDL, and file functions are denied by SQLite itself, including if a parser check is bypassed.
- **Local model boundary:** Ollama must be on loopback by default. A remote endpoint requires an explicit `ALLOW_REMOTE_OLLAMA=true` opt-in because schemas and SQL are sent to the model.
- **Browser and API hardening:** same-origin CORS defaults, CSP/security headers, 110 KB request cap, and a per-client 30-request/minute limit reduce browser and resource-abuse exposure.
- **Privacy-preserving history:** the regression ledger retains a query fingerprint and aggregate performance only; raw SQL and DDL are not stored.
- **Browser history:** recent reports are stored in the browser's local storage only. Do not use the history feature for sensitive SQL unless this local persistence is appropriate for the machine and browser profile.

### Important limitations

- DDL is executed in the local sandbox. Use only schemas appropriate for SQLite.
- Benchmark timings are comparative measurements from synthetic data, not production-performance guarantees.
- An LLM can be wrong. Inspect the optimized query, index statements, result preview, and execution plans before adopting recommendations.
- The generic seeder prioritizes common table/column conventions. Complex constraints, generated columns, triggers, or domain-specific schemas may not receive a full synthetic dataset.

## 7. Project Structure

```text
QueryPerf-AI/
├── main.py                  # FastAPI application and routes
├── schemas.py               # Pydantic request/response contracts
├── requirements.txt         # Python dependencies
├── .env.example             # Ollama configuration template
├── services/
│   ├── ai_service.py        # Ollama JSON orchestration and local fallback
│   └── db_service.py        # sandbox, seeding, plans, timing, preview
└── static/
    ├── index.html           # Single-page interface and report screen
    └── app.js               # Fetch, rendering, export, and local history
```

## 8. Installation and Quick Start

### Prerequisites

- Python 3.10 or newer
- `pip`
- [Ollama](https://ollama.com/) for AI-powered analysis (optional; the local fallback remains available)

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
ollama pull llama3.2
pytest # to run the automated python test suite (optional)
uvicorn main:app --reload
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Use **Load Sample Demo Data**, then click **Analyze & Benchmark Query**.

## 9. Configuration

Copy `.env.example` to `.env` and adjust values as needed:

```dotenv
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Base URL of the local or reachable Ollama server. |
| `OLLAMA_MODEL` | `llama3.2` | Model sent to Ollama's `/api/chat` endpoint. |

When Ollama cannot be reached, returns invalid JSON, or does not satisfy the required schema, the backend intentionally falls back to the local deterministic linter. The results report indicates which analysis engine was used.

## 10. Demonstration Workflow

1. **Select a Sample Query**: In the top-left toolbar, choose a demo preset and click **Load** to populate the SQL Query and Schema DDL.
2. **Run Analysis**: Click **Analyze & Benchmark Query**. The backend seeds 1,200 rows in an isolated memory database, benchmarks both versions, and renders the report.
3. **Inspect the Visual Execution Plan**: Under the **Visual Execution Plan** tab, observe the side-by-side flow graph. Click nodes to open the inspector drawer.
4. **Check the Anti-Pattern Scanner**: Review detected smells and use the **Copy** button on any suggested rewrite.
5. **Explore the Query Rewrite Playground**: View the 3 candidate queries tested in the sandbox. Apply the `🏆 BEST REWRITE`.
6. **Review the Index Advisor**: View ranked indexes with their star ratings, estimated gains, and trade-offs.
7. **Simulate a Custom Index (Index Lab)**: Type or select a custom index and click **Simulate Index** to view its impact.
8. **View Benchmark Distribution Graphs**: Run the 25-iteration distribution to view the latency histogram and P95 numbers.
9. **Natural Language AI Copilot**: Click **AI SQL Copilot**, type an English prompt, and click **Generate & Optimize**.
10. **Analytics Dashboard**: Click **Analytics Dashboard** to see aggregate metrics across all runs.

## 11. Troubleshooting

| Symptom | Likely cause and resolution |
| --- | --- |
| `ModuleNotFoundError` when starting | Activate the virtual environment and run `pip install -r requirements.txt`. |
| Results show `Local deterministic linter` | Ollama is not running, the configured model is unavailable, or it returned invalid structured JSON. Start Ollama and run `ollama pull <model>`. |
| HTTP 400 for a query | Verify the query is a single read-only `SELECT`, `WITH`, or `EXPLAIN` statement and does not contain blocked keywords. |
| HTTP 400 for DDL | Ensure the schema is valid SQLite DDL and compatible with the generic synthetic data seeder. |
| Query is interrupted | Simplify the query; the sandbox deliberately stops database work after approximately three seconds. |
| Benchmark values vary slightly | Short duration measurements are subject to normal local scheduling and cache variance. Compare relative behavior rather than treating small differences as exact. |
| No optimized improvement | An index may be inapplicable, the predicate may remain non-SARGable, the dataset may be too small for a dramatic difference, or the original query may already be efficient. |

## 12. Future Enhancements

Potential extensions include schema-aware data-generation profiles, result equivalence tests between original and optimized SQL, and authenticated report sharing.

## License

No license file is currently included. Add a license before redistributing or publishing the project.
