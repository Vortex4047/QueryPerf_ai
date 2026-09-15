# Software Requirements Specification (SRS)
## QueryPerf AI — Next-Gen SQL Optimization Platform

---

## 1. Introduction

### 1.1 Purpose
The purpose of this Software Requirements Specification (SRS) is to describe the architecture, behavior, interfaces, functional capabilities, constraints, and operation of QueryPerf AI.

QueryPerf AI addresses a common problem in database development: developers often know a query is slow, but they struggle to definitively identify whether the root cause is a table scan, a non-SARGable predicate, unnecessary data retrieval, missing join indexes, or a combination of these factors. QueryPerf AI tests recommendations against a newly seeded sandbox and presents empirical timing data, bridging the gap between theoretical query analysis and practical performance benchmarking.

### 1.2 Document Conventions
| Convention | Meaning |
| --- | --- |
| `inline code` | File names, commands, configuration variables, SQL, API routes, and JSON fields. |
| **Bold text** | Important concepts, requirements, or cautions. |
| `GET /api/health` | An HTTP method followed by its route. |
| `:memory:` | A new, ephemeral SQLite database stored only in process memory. |

All SQL examples use SQLite-compatible syntax. Measured time is expressed in milliseconds (`ms`).

### 1.3 Intended Audience
This document serves several audiences:
- **Project Evaluators/Instructors**: Introduction, Product Scope, Architecture, Benchmarking Method, Security Model.
- **Developers**: API Reference, Architecture, Testing & Setup.
- **Database Students/SQL Learners**: Core Concepts, Functional Requirements, User Guide.

### 1.4 Product Scope
QueryPerf AI is a single-page web application with a Python/FastAPI backend and an in-memory database benchmark sandbox (supporting SQLite, PostgreSQL, and MySQL simulation features). The user submits DDL and a read-only SQL query. The system then:
- Validates the query and creates a fresh sandbox.
- Creates the submitted schema and inserts approximately 1,200 deterministic synthetic records per compatible table.
- Captures the `EXPLAIN QUERY PLAN` output for the original query.
- Analyzes the query using a local deterministic linter (18+ rules) or an AI model (like local Ollama).
- Identifies bottlenecks and generates rewrite candidates.
- Applies safe `CREATE INDEX` recommendations.
- Compares execution plans and empirically benchmarks the queries over multiple iterations (5 iterations by default).
- Renders a comprehensive performance report.

---

## 2. Core Concepts

### 2.1 SARGability
A predicate is **SARGable** (Search ARGument ABLE) when the database can use an index to locate matching values directly. 
- *SARGable*: `WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'`
- *Non-SARGable*: `WHERE strftime('%Y', order_date) = '2025'` (Requires calculating `strftime` for candidate rows, defeating index lookups).

### 2.2 Table Scans and B-Tree Indexes
A full-table scan visits every row in a table; its cost grows linearly with table size. A B-tree index makes selective lookup and join operations faster, approaching logarithmic lookup times. QueryPerf AI balances performance gains with the real-world trade-offs of B-Tree storage size and write latency.

### 2.3 SQL Anti-Patterns
The system enforces 18+ deterministic rules to catch common SQL anti-patterns, including:
1. `SELECT *` Column Projections
2. `OR in WHERE` clause (defeats single index seek)
3. `NOT IN (subquery)` NULL trap & unindexed scan
4. `IN (subquery)` vs `EXISTS` semi-join
5. Functions / Expressions on indexed columns (Non-SARGable `strftime`, `date`, `lower`, `substr`)
6. Leading wildcard searches (`LIKE '%...'`)
7. Unnecessary `DISTINCT`, `GROUP BY` without aggregate, `ORDER BY` without `LIMIT`
8. Repeated duplicate subqueries and Correlated subqueries in projections/filters (O(N*M) runtime)
9. Implicit type conversions in predicates
10. Cartesian joins (`CROSS JOIN` or multiple tables with missing `ON`) and Missing `JOIN` predicates
11. `HAVING` used for non-aggregate filtering
12. Redundant joined tables, `SELECT *` inside CTEs, and Redundant nested `SELECT` wrappers

---

## 3. System Architecture

### 3.1 High-Level Architecture
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
│ Database Sandbox Service       │      │ AI / Linter Service        │
│ fresh :memory: connection      │      │ deterministic linter       │
│ synthetic data seeding         │      │ structured JSON output     │
│ plans + benchmark + preview    │      └────────────────────────────┘
└───────────────────────────────┘
```

### 3.2 Request Processing Pipeline
1. Frontend sends `ddl_schema` and `slow_query` to `POST /api/optimize`.
2. Pydantic validates payload constraints.
3. The sandbox service enforces a strict read-only query policy.
4. A fresh sandbox database is spawned, DDL is executed, and synthetic data is seeded.
5. The execution plan for the original query is captured.
6. The linter (or Ollama model) analyzes the DDL, query, and plan to generate JSON recommendations.
7. A new query version and optimal index(es) are generated. The sandbox validates and applies the new indexes.
8. Both the original and optimized queries are benchmarked over multiple iterations.
9. An aggregated report (scores, timings, plans, previews) is returned to the client.

---

## 4. Functional Requirements

QueryPerf AI encompasses 12 core capabilities:

1. **Interactive Visual Execution Plan Tree**: Converts raw `EXPLAIN QUERY PLAN` output into a hierarchical tree. Clicking any node opens a physical operator inspection drawer detailing exact target tables, operation type, relative cost bar, and plain-English explanations of disk/memory I/O impacts.
2. **SQL Anti-Pattern Scanner**: Detects 18+ rules, evaluates severity (CRITICAL, HIGH, MEDIUM, LOW), and provides an estimated impact along with a suggested one-click rewrite.
3. **Query Rewrite Playground**: Generates 3 intelligent refactoring candidates (e.g., SARGable conversions, `EXISTS` refactors, CTE filters). These are executed live across 5 iterations in the sandbox, dynamically flagging the fastest as the `🏆 BEST REWRITE`.
4. **Advanced Index Advisor with Cost/Benefit**: Synthesizes single and composite indexes from query filters/join keys, applies them dynamically, benchmarks them, and assigns a ⭐ 1-100 star rating while detailing clear Trade-Off Advantages (+) and Trade-Off Costs (−).
5. **Benchmark Graphs & Distribution**: Visualizes execution latency, CPU time, estimated plan-derived I/O reads, and output rows. Users can run 25 consecutive iterations to generate a 5-bucket latency histogram and min, max, median, P95 metrics.
6. **Interactive What-If Index Simulator (Index Lab)**: Allows users to simulate any custom `CREATE INDEX ...` statement (with quick-fill buttons) in an isolated SQLite transaction savepoint (`SAVEPOINT`), benchmarks it, compares plans, reports the verdict (Useful, Neutral, Redundant), and rolls back safely.
7. **Query Complexity Analysis**: Counts JOINs, Subqueries, Aggregations, Sorts, and Filters to evaluate overall Complexity Risk (`LOW`, `MEDIUM`, `HIGH`) and identifies dominant cost factors (e.g., Unbounded Sort Buffer).
8. **Multi-Database Engine Selector**: Allows users to switch parsing/display contexts between SQLite (Live Sandbox), PostgreSQL (displays `EXPLAIN (ANALYZE, BUFFERS)` plans), and MySQL (displays `EXPLAIN ANALYZE` plans).
9. **Natural Language to SQL Copilot**: An AI-powered modal that converts English prompts into schema-aware SQL using local Ollama or deterministic heuristic parsing, and pipes it directly into the optimization engine.
10. **Query Regression Detection**: Continuously checks if a query executes slower than its historical baseline (stored in `.queryperf_history.sqlite`), triggering a prominent alert banner on regression with percentage differences.
11. **Query Performance Analytics Dashboard**: A modal displaying aggregate KPIs (Total queries analyzed, Average speedup, Total regressions detected, Top slowest queries ledger, and Anti-pattern frequencies distribution).
12. **Optimization Confidence Score**: An objective 0-100 scorecard verifying plan improvements (e.g., scan to indexed seek: +30%), latency reduction (+30%), result set integrity non-empty (+20%), sandbox index verification (+10%), and read-only safety (+10%).

---

## 5. External Interface Requirements (API)

FastAPI exposes interactive API documentation at `http://127.0.0.1:8000/docs`.

### 5.1 `GET /api/health`
Returns a lightweight service-health response.
```json
{
  "status": "ok",
  "service": "QueryPerf AI"
}
```

### 5.2 `POST /api/optimize`
Submits a schema and a read-only query for optimization.
**Request:**
```json
{
  "ddl_schema": "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);",
  "slow_query": "SELECT * FROM items WHERE name LIKE '%demo%';"
}
```
**Response Yields:**
- `health_score_original` & `health_score_optimized`
- `detected_anti_patterns`
- `optimized_query` & `index_recommendations`
- `original_ms` & `optimized_ms` (and speedup factor)
- `original_execution_plan` & `optimized_execution_plan`
- `optimized_preview` (sample result rows)

**Error Handling:**
- `400 Bad Request`: Invalid DDL, unsafe SQL, SQLite error.
- `422 Unprocessable Entity`: Schema validation failures.
- `500 Internal Server Error`: Unexpected backend exceptions.

---

## 6. Security Model and Constraints

### 6.1 Sandboxing and Validations
- **Fresh database per operation**: Each sandbox uses a disposable `:memory:` SQLite database or a strictly isolated transaction.
- **Read-only input policy**: User queries must begin with `SELECT`, `WITH`, or `EXPLAIN`.
- **Blocked Operations**: Destructive DDL/DML (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `PRAGMA`) are strictly denied by the validator.
- **Single-statement policy**: Embedded extra statements (SQL injection vectors) are rejected.
- **Time limits**: A 3-second busy timeout prevents long-running queries from locking up the application.
- **SQLite VM Authorization**: Internal hooks deny file attachments, extensions, triggers, views, virtual tables, or unsafe functions.

### 6.2 Limitations
- **Synthetic Data Discrepancies**: Benchmark timings are comparative measurements derived from synthetic data, not exact production performance guarantees.
- **Schema Compatibility**: DDL executed in the sandbox must be SQLite-compatible. Highly engine-specific triggers or constraints may not seed properly.
- **AI Hallucinations**: When the Ollama fallback is enabled, an LLM might generate invalid statements. The sandbox intercepts and prevents these from causing crashes, but manual inspection is still recommended.

---

## 7. Testing and Verification

The system maintains an **Automated Python Test Suite** (23 passing tests executed via `pytest`).
Tested areas include:
- **API Handlers** (`test_api.py`): Dashboard, health, NL-to-SQL, schema completions, optimization endpoints.
- **SQL Linter** (`test_linter.py`): Exact detection capabilities for Cartesian products, wildcards, non-SARGable functions, NOT IN, etc.
- **Plan Visualizer** (`test_plan_visualizer.py`): Parsing execution plans from SQLite, MySQL, and PostgreSQL formats.
- **Database Sandbox** (`test_sandbox.py`): End-to-end sandbox pipeline execution, benchmark distribution generation, rewrite candidate compilation, and What-If index simulation integrity.

---

## 8. Configuration & Setup

### 8.1 Prerequisites
- Python 3.10 or newer
- `pip`
- [Ollama](https://ollama.com/) (optional, local deterministic linter runs seamlessly without it).

### 8.2 Installation Steps
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
ollama pull llama3.2    # (Optional) pull the AI model
pytest                  # (Optional) verify the automated test suite passes
uvicorn main:app --reload --port 8000
```
Then open **`http://127.0.0.1:8000`** in your browser.

### 8.3 Environment Variables (`.env`)
| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Base URL of the local or reachable Ollama server. |
| `OLLAMA_MODEL` | `llama3.2` | Model sent to Ollama's `/api/chat` endpoint. |

---

## 9. User Guide & Demonstration Workflow

1. **Select a Sample Query**: In the top-left toolbar, choose a demo preset (e.g. `Sample: Non-SARGable E-Commerce Join`) and click **Load** to populate the SQL Query and Schema DDL.
2. **Run Analysis**: Click **Analyze & Benchmark Query**. The backend seeds rows in the memory database, benchmarks versions, and renders the report.
3. **Inspect the Visual Execution Plan**: Under the **Visual Execution Plan** tab, observe the flow graph. Click the red `SCAN` node to open the inspector drawer, and contrast it with the green `INDEX SEEK` node.
4. **Check the Anti-Pattern Scanner**: Review detected smells and use the **Copy** button on any suggested rewrite.
5. **Explore the Query Rewrite Playground**: View the 3 candidate queries tested in the sandbox. Apply the `🏆 BEST REWRITE`.
6. **Review the Index Advisor**: View ranked indexes with their star ratings, estimated gains, and trade-offs.
7. **Simulate a Custom Index (Index Lab)**: Click one of the quick presets (e.g. `+ orders(customer_id, status)`), then click **Simulate Index** to view its impact on plan and latency.
8. **View Benchmark Distribution Graphs**: Click **Run 25-Iteration Distribution** to execute 25 benchmark runs and view the latency histogram and P95 numbers.
9. **Natural Language AI Copilot**: Click **AI SQL Copilot**, type an English prompt, and click **Generate & Optimize**.
10. **Analytics Dashboard**: Click **Analytics Dashboard** to see aggregate metrics across all historical runs.

---

## 10. Future Enhancements

Potential extensions include:
- Schema-aware data-generation profiles for highly specific synthetic data shaping.
- Result equivalence tests between original and optimized SQL statements.
- Authenticated report sharing for collaborative query tuning in teams.
