import re
import sqlite3
from schemas import IndexCostBenefit


class AdvancedIndexAdvisor:
    """Analyzes query predicates and dynamically tests candidate indexes in the sandbox."""

    def advise(
        self,
        cursor: sqlite3.Cursor,
        original_query: str,
        optimized_query: str,
        baseline_ms: float,
        benchmark_fn,
        plan_fn,
    ) -> list[IndexCostBenefit]:
        candidates: list[IndexCostBenefit] = []
        q = original_query.lower()

        # Extract table names and potential columns from query
        table_cols = self._extract_table_columns(original_query)
        if not table_cols:
            return []

        # Generate candidate index statements tailored to the query
        candidate_statements = self._generate_candidate_indexes(original_query, table_cols)

        # Empirically measure each candidate index in the SQLite sandbox
        base_plan = plan_fn(cursor, optimized_query)

        for stmt in candidate_statements:
            match = re.search(r"create\s+(?:unique\s+)?index\s+(?:if\s+not\s+exists\s+)?(\w+)\s+on\s+(\w+)\s*\(([^)]+)\)", stmt, re.IGNORECASE)
            if not match:
                continue
            idx_name, table, cols_str = match.groups()
            cols = [c.strip() for c in cols_str.split(",")]

            try:
                cursor.execute("SAVEPOINT advisor_trial")
                cursor.execute(stmt)

                trial_plan = plan_fn(cursor, optimized_query)
                trial_ms, _, _ = benchmark_fn(cursor, optimized_query, iterations=5)

                cursor.execute("ROLLBACK TO advisor_trial")
                cursor.execute("RELEASE advisor_trial")

                # Dynamic calculation of metrics based on actual execution
                speedup_pct = max(0.0, round(((baseline_ms - trial_ms) / max(baseline_ms, 0.001)) * 100, 1))
                improvement_ms = max(0.0, round(baseline_ms - trial_ms, 3))
                plan_changed = trial_plan.strip() != base_plan.strip()
                eliminated_scan = ("scan" in base_plan.lower()) and not ("scan" in trial_plan.lower())
                used_index = idx_name.lower() in trial_plan.lower()

                # Calculate star rating dynamically from real impact
                if used_index or eliminated_scan:
                    star_rating = min(99, max(65, int(60 + (speedup_pct * 0.4))))
                elif plan_changed:
                    star_rating = min(75, max(45, int(45 + (speedup_pct * 0.3))))
                else:
                    # Optimizer rejected index
                    star_rating = max(15, min(35, int(30 - (trial_ms * 2))))

                pros = [
                    f"Provides B-Tree access path on table '{table}' for columns ({', '.join(cols)})",
                ]
                if eliminated_scan:
                    pros.append(f"Directly eliminated sequential full table scan on '{table}'")
                if speedup_pct > 15:
                    pros.append(f"Measured {speedup_pct}% empirical latency reduction in sandbox")

                cons = [
                    f"Consumes ~{len(cols) * 16 + 12} bytes per row in B-Tree index pages",
                    f"Adds minor CPU and disk I/O overhead during INSERT/UPDATE/DELETE on '{table}'"
                ]

                candidates.append(IndexCostBenefit(
                    index_name=idx_name,
                    table=table,
                    columns=cols,
                    command=stmt,
                    estimated_benefit_percent=speedup_pct,
                    query_improvement_ms=improvement_ms,
                    before_ms=baseline_ms,
                    after_ms=trial_ms,
                    star_rating=star_rating,
                    tradeoffs_pros=pros,
                    tradeoffs_cons=cons,
                ))
            except Exception:
                # If candidate index fails to apply (e.g. invalid column name), safely skip
                try:
                    cursor.execute("ROLLBACK TO advisor_trial")
                    cursor.execute("RELEASE advisor_trial")
                except Exception:
                    pass

        # Sort dynamically by star rating descending
        candidates.sort(key=lambda x: (x.star_rating, x.estimated_benefit_percent), reverse=True)
        return candidates

    def _extract_table_columns(self, query: str) -> dict[str, list[str]]:
        """Extracts referenced tables and columns from SQL query."""
        res: dict[str, list[str]] = {}
        # Find FROM and JOIN clauses
        from_matches = re.findall(r"\b(?:from|join)\s+([\w]+)(?:\s+as\s+([\w]+)|\s+([\w]+))?", query, re.IGNORECASE)
        table_aliases = {}
        for match in from_matches:
            tbl = match[0]
            alias = match[1] or match[2] or tbl
            table_aliases[alias] = tbl
            if tbl not in res:
                res[tbl] = []

        # Find column references alias.col
        col_refs = re.findall(r"\b([\w]+)\.([\w]+)\b", query)
        for alias, col in col_refs:
            if alias in table_aliases:
                tbl = table_aliases[alias]
                if col not in res[tbl]:
                    res[tbl].append(col)

        return res

    def _generate_candidate_indexes(self, query: str, table_cols: dict[str, list[str]]) -> list[str]:
        statements: list[str] = []
        q_lower = query.lower()

        for table, cols in table_cols.items():
            if not cols:
                continue

            # Prioritize filter and join columns
            filter_cols = [c for c in cols if c in q_lower and ("where" in q_lower or "join" in q_lower)]
            other_cols = [c for c in cols if c not in filter_cols]

            # Single-column candidate
            if filter_cols:
                primary_col = filter_cols[0]
                statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_{primary_col} ON {table}({primary_col});")

            # Composite candidate (Join column + Filter column)
            if len(cols) >= 2:
                comp_cols = (filter_cols + other_cols)[:2]
                statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_{'_'.join(comp_cols)} ON {table}({', '.join(comp_cols)});")

            # Special case for order_date / status if in query
            if "order_date" in cols and "status" in cols:
                statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_status_date ON {table}(status, order_date);")

        return list(dict.fromkeys(statements))
