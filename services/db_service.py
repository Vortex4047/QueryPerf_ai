import re
import sqlite3
import time
from dataclasses import dataclass
from schemas import (BenchmarkDistributionResponse, RewriteCandidate, VisualPlanNode,
                     WhatIfSimResponse)
from services.plan_visualizer import PlanVisualizerService


FORBIDDEN = re.compile(r"\b(drop|delete|update|insert|alter|truncate|pragma|attach|detach|vacuum|replace)\b", re.I)
ALLOWED_START = re.compile(r"^\s*(select|with|explain)\b", re.I)
CREATE_INDEX = re.compile(r"^\s*create\s+(?:unique\s+)?index\b", re.I)


@dataclass
class BenchmarkResult:
    execution_plan: str
    optimized_execution_plan: str
    original_ms: float
    optimized_ms: float
    optimized_preview_columns: list[str]
    optimized_preview_rows: list[list[str]]
    original_cpu_ms: float
    optimized_cpu_ms: float
    original_io_reads: int
    optimized_io_reads: int
    original_rows: int
    optimized_rows: int
    what_if_indexes: list[dict]


class DatabaseSandboxService:
    """Creates a new, short-lived SQLite database for every analysis operation."""

    def __init__(self):
        self.visualizer = PlanVisualizerService()

    def validate_read_only_query(self, sql_query: str) -> None:
        query = sql_query.strip().rstrip(";").strip()
        if not ALLOWED_START.match(query):
            raise ValueError("Only SELECT, WITH, or EXPLAIN queries are allowed in the sandbox.")
        if FORBIDDEN.search(query):
            raise ValueError("The query contains a prohibited SQL operation. Only read-only SQL is allowed.")
        if ";" in query:
            raise ValueError("Only one SQL statement may be submitted.")

    @staticmethod
    def _authorizer(action: int, arg1: str | None, arg2: str | None, database: str | None, trigger: str | None) -> int:
        """Defense in depth: reject file, extension, and schema-changing opcodes at SQLite's VM boundary."""
        denied = {
            sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA,
            sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_TEMP_INDEX,
            sqlite3.SQLITE_DROP_TEMP_TABLE, sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW, sqlite3.SQLITE_DROP_TEMP_VIEW, sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW, sqlite3.SQLITE_CREATE_TEMP_VIEW, sqlite3.SQLITE_CREATE_VTABLE,
        }
        dangerous_functions = {"load_extension", "readfile", "writefile"}
        if action in denied or (action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").lower() in dangerous_functions):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @staticmethod
    def _connection() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", timeout=3.0)
        conn.execute("PRAGMA busy_timeout = 3000")
        if hasattr(conn, "enable_load_extension"):
            conn.enable_load_extension(False)
        conn.set_authorizer(DatabaseSandboxService._authorizer)
        deadline = time.perf_counter() + 3.0
        conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10_000)
        return conn

    def _initialize(self, ddl: str) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
        conn = self._connection()
        cursor = conn.cursor()
        try:
            cursor.executescript(ddl)
            conn.set_authorizer(None)
            self.seed_synthetic_data(cursor, ddl)
            conn.commit()
            conn.set_authorizer(self._authorizer)
            return conn, cursor
        except (sqlite3.Error, ValueError) as exc:
            conn.set_authorizer(self._authorizer)
            conn.close()
            raise ValueError(f"Invalid DDL schema: {exc}") from exc

    @staticmethod
    def _value_for(column: str, column_type: str, row: int, table: str):
        lower = column.lower()
        type_lower = (column_type or "").lower()
        if "id" in lower or "int" in type_lower:
            return ((row - 1) % 1200) + 1
        if "email" in lower:
            return f"user{row}@queryperf.demo"
        if "date" in lower or "time" in lower:
            return f"2025-{((row - 1) % 12) + 1:02d}-{((row - 1) % 28) + 1:02d}"
        if "status" in lower:
            return ("DELIVERED" if row % 3 else "PENDING")
        if any(token in lower for token in ("amount", "price", "cost", "total", "balance")) or any(token in type_lower for token in ("real", "decimal", "numeric", "float", "double")):
            return round(10 + (row * 7.31) % 990, 2)
        if "bool" in type_lower:
            return row % 2
        return f"{table}_{column}_{row}"

    def seed_synthetic_data(self, cursor: sqlite3.Cursor, ddl: str) -> None:
        """Populate user-created tables deterministically, without depending on a known schema."""
        tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        tables.sort(key=lambda name: ("order" in name.lower() or "item" in name.lower(), name))
        for table in tables:
            quoted_table = '"' + table.replace('"', '""') + '"'
            columns = cursor.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            insertable = [column for column in columns if not (column[5] and "int" in (column[2] or "").lower())]
            if not insertable:
                continue
            names = [column[1] for column in insertable]
            quoted_names = ", ".join('"' + name.replace('"', '""') + '"' for name in names)
            placeholders = ", ".join("?" for _ in names)
            sql = f"INSERT OR IGNORE INTO {quoted_table} ({quoted_names}) VALUES ({placeholders})"
            rows = [tuple(self._value_for(column[1], column[2], row, table) for column in insertable) for row in range(1, 1201)]
            try:
                cursor.executemany(sql, rows)
            except sqlite3.Error:
                continue

    def get_execution_plan(self, cursor: sqlite3.Cursor, query: str) -> str:
        self.validate_read_only_query(query)
        try:
            rows = cursor.execute("EXPLAIN QUERY PLAN " + query.rstrip("; ")).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f"SQLite could not explain the query: {exc}") from exc
        return "\n".join(f"[{row[0]}:{row[1]}] {row[3]}" for row in rows) or "SQLite returned no plan steps."

    def _capped_query(self, query: str) -> str:
        return f"SELECT * FROM ({query.rstrip('; ')}) AS queryperf_safe_limit LIMIT 250"

    def benchmark_query(self, cursor: sqlite3.Cursor, query: str, iterations: int = 5) -> tuple[float, float, int]:
        self.validate_read_only_query(query)
        elapsed, cpu_elapsed = [], []
        try:
            for _ in range(iterations):
                started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
                rows = cursor.execute(self._capped_query(query)).fetchall()
                elapsed.append((time.perf_counter_ns() - started) / 1_000_000)
                cpu_elapsed.append((time.process_time_ns() - cpu_started) / 1_000_000)
        except sqlite3.Error as exc:
            raise ValueError(f"SQLite could not execute the query: {exc}") from exc
        return round(sum(elapsed) / len(elapsed), 4), round(sum(cpu_elapsed) / len(cpu_elapsed), 4), len(rows)

    @staticmethod
    def estimate_io_reads(plan: str) -> int:
        return plan.lower().count("scan") * 1200 + plan.lower().count("search") * 24

    def preview_query(self, cursor: sqlite3.Cursor, query: str, limit: int = 5) -> tuple[list[str], list[list[str]]]:
        self.validate_read_only_query(query)
        try:
            cursor.execute(query.rstrip("; "))
            columns = [item[0] for item in (cursor.description or [])]
            rows = [["NULL" if value is None else str(value) for value in row] for row in cursor.fetchmany(limit)]
            return columns, rows
        except sqlite3.Error as exc:
            raise ValueError(f"SQLite could not preview the optimized query: {exc}") from exc

    def preview_execution_plan(self, ddl: str, query: str) -> str:
        conn, cursor = self._initialize(ddl)
        try:
            return self.get_execution_plan(cursor, query)
        finally:
            conn.close()

    def execute_full_suite(
        self,
        ddl: str,
        original_query: str,
        optimized_query: str,
        index_commands: list[str],
        raw_candidates: list[dict],
    ):
        """Executes full optimization suite inside a single live sandbox with real measurements."""
        self.validate_read_only_query(original_query)
        self.validate_read_only_query(optimized_query)
        from services.index_advisor import AdvancedIndexAdvisor
        advisor = AdvancedIndexAdvisor()

        conn, cursor = self._initialize(ddl)
        try:
            # 1. Baseline measurements
            plan = self.get_execution_plan(cursor, original_query)
            original_ms, original_cpu_ms, original_rows = self.benchmark_query(cursor, original_query)

            # 2. What-If verification for recommended indexes
            what_if_indexes = []
            for command in index_commands:
                if not CREATE_INDEX.match(command) or ";" in command.strip().rstrip(";"):
                    raise ValueError("Only a single CREATE INDEX statement may be applied as an optimization.")
                try:
                    cursor.execute("SAVEPOINT queryperf_what_if")
                    before_ms = original_ms
                    cursor.execute(command)
                    trial_plan = self.get_execution_plan(cursor, optimized_query)
                    trial_ms, _, _ = self.benchmark_query(cursor, optimized_query)
                    what_if_indexes.append({
                        "index_command": command,
                        "before_ms": before_ms,
                        "after_ms": trial_ms,
                        "estimated_gain_percent": round(max(0.0, (before_ms - trial_ms) / max(before_ms, .001) * 100), 1),
                        "plan_changed": trial_plan != plan
                    })
                    cursor.execute("ROLLBACK TO queryperf_what_if")
                    cursor.execute("RELEASE queryperf_what_if")
                    cursor.execute(command)
                except sqlite3.Error as exc:
                    raise ValueError(f"An index recommendation could not be applied: {exc}") from exc

            # 3. Optimized query measurements
            optimized_plan = self.get_execution_plan(cursor, optimized_query)
            optimized_ms, optimized_cpu_ms, optimized_rows = self.benchmark_query(cursor, optimized_query)
            preview_columns, preview_rows = self.preview_query(cursor, optimized_query)

            # 4. Measure Rewrite Candidates in the exact same sandbox
            rewrite_results: list[RewriteCandidate] = []
            for cand in raw_candidates:
                try:
                    cand_ms, cand_cpu, _ = self.benchmark_query(cursor, cand["query"])
                    cand_plan = self.get_execution_plan(cursor, cand["query"])
                    speedup = round(max(0.0, (original_ms - cand_ms) / max(original_ms, 0.001) * 100), 1)
                    rewrite_results.append(RewriteCandidate(
                        id=cand["id"],
                        title=cand["title"],
                        strategy=cand["strategy"],
                        query=cand["query"],
                        execution_ms=cand_ms,
                        cpu_ms=cand_cpu,
                        plan_summary=cand_plan.splitlines()[0] if cand_plan else "Evaluated",
                        is_best=False,
                        speedup_percent=speedup,
                    ))
                except Exception:
                    continue

            if rewrite_results:
                best = min(rewrite_results, key=lambda r: r.execution_ms)
                best.is_best = True

            # 5. Measure Candidate Index Advisor options dynamically in the sandbox
            index_advisor_results = advisor.advise(
                cursor=cursor,
                original_query=original_query,
                optimized_query=optimized_query,
                baseline_ms=original_ms,
                benchmark_fn=self.benchmark_query,
                plan_fn=self.get_execution_plan,
            )

            benchmark_res = BenchmarkResult(
                plan, optimized_plan, original_ms, optimized_ms, preview_columns, preview_rows,
                original_cpu_ms, optimized_cpu_ms, self.estimate_io_reads(plan), self.estimate_io_reads(optimized_plan),
                original_rows, optimized_rows, what_if_indexes
            )

            return benchmark_res, rewrite_results, index_advisor_results
        finally:
            conn.close()

    def execute_sandbox_pipeline(self, ddl: str, original_query: str, optimized_query: str, index_commands: list[str]) -> BenchmarkResult:
        res, _, _ = self.execute_full_suite(ddl, original_query, optimized_query, index_commands, [])
        return res

    def benchmark_rewrite_candidates(self, ddl: str, original_query: str, raw_candidates: list[dict], index_commands: list[str]) -> list[RewriteCandidate]:
        """Runs and benchmarks each rewrite candidate in the seeded sandbox."""
        conn, cursor = self._initialize(ddl)
        try:
            # Apply verified indexes first
            for cmd in index_commands:
                try:
                    cursor.execute(cmd)
                except sqlite3.Error:
                    pass

            base_ms, _, _ = self.benchmark_query(cursor, original_query)
            results: list[RewriteCandidate] = []

            for cand in raw_candidates:
                try:
                    cand_ms, cand_cpu, _ = self.benchmark_query(cursor, cand["query"])
                    plan = self.get_execution_plan(cursor, cand["query"])
                    speedup = round(max(0, (base_ms - cand_ms) / max(base_ms, 0.001) * 100), 1)
                    results.append(RewriteCandidate(
                        id=cand["id"],
                        title=cand["title"],
                        strategy=cand["strategy"],
                        query=cand["query"],
                        execution_ms=cand_ms,
                        cpu_ms=cand_cpu,
                        plan_summary=plan.splitlines()[0] if plan else "Evaluated",
                        is_best=False,
                        speedup_percent=speedup,
                    ))
                except Exception:
                    continue

            if results:
                # Mark candidate with lowest execution_ms as best
                best = min(results, key=lambda r: r.execution_ms)
                best.is_best = True

            return results
        finally:
            conn.close()

    def simulate_custom_index(self, ddl: str, query: str, index_command: str) -> WhatIfSimResponse:
        """Interactive What-If Index Simulator (Index Lab). Tests custom index in sandbox with savepoint rollback."""
        self.validate_read_only_query(query)
        if not CREATE_INDEX.match(index_command.strip()) or ";" in index_command.strip().rstrip(";"):
            raise ValueError("The Index Simulator accepts only a single valid CREATE [UNIQUE] INDEX statement.")

        conn, cursor = self._initialize(ddl)
        try:
            # Measure baseline
            plan_before = self.get_execution_plan(cursor, query)
            before_ms, _, _ = self.benchmark_query(cursor, query, iterations=5)

            # Apply candidate index under transaction savepoint
            cursor.execute("SAVEPOINT index_lab_trial")
            try:
                cursor.execute(index_command)
                plan_after = self.get_execution_plan(cursor, query)
                after_ms, _, _ = self.benchmark_query(cursor, query, iterations=5)
            except sqlite3.Error as exc:
                cursor.execute("ROLLBACK TO index_lab_trial")
                cursor.execute("RELEASE index_lab_trial")
                raise ValueError(f"SQLite could not apply index: {exc}") from exc

            cursor.execute("ROLLBACK TO index_lab_trial")
            cursor.execute("RELEASE index_lab_trial")

            plan_changed = (plan_before.strip() != plan_after.strip())
            speedup = round(max(0, (before_ms - after_ms) / max(before_ms, 0.001) * 100), 1)

            if plan_changed and (before_ms > after_ms or speedup > 5):
                verdict = "Useful"
                explanation = f"SQLite utilized the new index! Execution plan eliminated scan operations and speedup was measured at {speedup}% ({before_ms:.3f} ms → {after_ms:.3f} ms)."
            elif plan_changed:
                verdict = "Neutral"
                explanation = f"SQLite adopted the index in its plan, but timing in this sandbox showed negligible speedup ({before_ms:.3f} ms → {after_ms:.3f} ms)."
            else:
                verdict = "Redundant"
                explanation = "SQLite query planner did NOT select this index for the query. The execution plan remained identical."

            return WhatIfSimResponse(
                index_command=index_command,
                valid=True,
                verdict=verdict,
                before_ms=before_ms,
                after_ms=after_ms,
                speedup_percent=speedup,
                explanation=explanation,
                plan_before=plan_before,
                plan_after=plan_after,
                visual_plan_before=self.visualizer.parse_sqlite_plan(plan_before),
                visual_plan_after=self.visualizer.parse_sqlite_plan(plan_after),
            )
        finally:
            conn.close()

    def benchmark_distribution(self, ddl: str, query: str, iterations: int = 25) -> BenchmarkDistributionResponse:
        """Executes query N times and computes percentile distributions and histogram buckets."""
        self.validate_read_only_query(query)
        conn, cursor = self._initialize(ddl)
        try:
            samples: list[float] = []
            for _ in range(iterations):
                start = time.perf_counter_ns()
                cursor.execute(self._capped_query(query)).fetchall()
                samples.append(round((time.perf_counter_ns() - start) / 1_000_000, 4))

            samples.sort()
            min_ms = samples[0]
            max_ms = samples[-1]
            median_ms = samples[len(samples) // 2]
            avg_ms = round(sum(samples) / len(samples), 4)
            p95_idx = int(len(samples) * 0.95)
            p95_ms = samples[min(p95_idx, len(samples) - 1)]

            # Generate 5 distribution buckets for visualization
            span = max(0.01, (max_ms - min_ms))
            bucket_width = span / 5
            buckets = []
            for i in range(5):
                b_min = min_ms + (i * bucket_width)
                b_max = b_min + bucket_width
                count = sum(1 for s in samples if (b_min <= s < b_max) or (i == 4 and b_min <= s <= b_max))
                buckets.append({
                    "range_label": f"{b_min:.2f} - {b_max:.2f} ms",
                    "count": count,
                    "percentage": round((count / len(samples)) * 100, 1)
                })

            return BenchmarkDistributionResponse(
                iterations=iterations,
                min_ms=min_ms,
                max_ms=max_ms,
                median_ms=median_ms,
                avg_ms=avg_ms,
                p95_ms=p95_ms,
                samples=samples,
                distribution_buckets=buckets,
            )
        finally:
            conn.close()
