import re
from schemas import AntiPattern, QueryComplexity


class SQLLinterService:
    """Detects 18+ SQL anti-patterns with severity, impact, explanation, and rewrite guidance."""

    def scan_anti_patterns(self, query: str, plan_text: str = "") -> list[AntiPattern]:
        findings: list[AntiPattern] = []
        q_clean = query.strip()
        q_lower = q_clean.lower()

        # 1. SELECT *
        if re.search(r"\bselect\s+\*", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="SELECT * Projections",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="Retrieving all columns inflates network payload, I/O bandwidth, and prevents index-only covering scans.",
                suggested_rewrite="Explicitly enumerate only the required column projections (e.g. SELECT c.id, c.name).",
                category="I/O & Memory",
            ))

        # 2. OR in WHERE clause
        if re.search(r"\bwhere\b[^\;]+?\bor\b", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="OR Condition in WHERE Clause",
                severity="HIGH",
                estimated_impact="High",
                why="OR conditions frequently defeat single-index b-tree seeks, forcing full table scans or multiple index merges.",
                suggested_rewrite="Refactor into a UNION ALL of two indexed SELECT branches, or use an IN (...) list if on the same column.",
                category="Index Utilization",
            ))

        # 3. NOT IN with Subquery / Null hazard
        if re.search(r"\bnot\s+in\s*\(", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="NOT IN Subquery / List",
                severity="HIGH",
                estimated_impact="High",
                why="NOT IN evaluates to UNKNOWN if the subquery returns any NULL value, disabling index seeks and forcing nested loops.",
                suggested_rewrite="Rewrite using NOT EXISTS (SELECT 1 FROM ...) or a LEFT JOIN with WHERE right_key IS NULL.",
                category="SARGability & Correctness",
            ))

        # 4. IN Subquery instead of EXISTS
        if re.search(r"\bwhere\b[^\;]+?\bin\s*\(\s*select\b", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="IN (Subquery) Instead of EXISTS",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="IN subqueries may materialize the entire inner result set into a temporary table before matching.",
                suggested_rewrite="Rewrite as EXISTS (SELECT 1 FROM ...) which short-circuits on the first matching record.",
                category="Query Structure",
            ))

        # 5. Functions / Expressions on Filtered Columns (Non-SARGable)
        if re.search(r"\b(strftime|date|lower|upper|substr|abs|round|coalesce)\s*\(", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="Function / Expression on Indexed Column",
                severity="CRITICAL",
                estimated_impact="High",
                why="Wrapping column references in scalar functions prevents the database optimizer from performing binary B-Tree range seeks.",
                suggested_rewrite="Transform the condition so the bare column is compared against constant boundaries (e.g. col >= '2025-01-01' AND col < '2026-01-01').",
                category="SARGability",
            ))

        # 6. Leading Wildcard LIKE
        if re.search(r"\blike\s+['\"][%_]", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="Leading Wildcard Search (LIKE '%...')",
                severity="HIGH",
                estimated_impact="High",
                why="Leading wildcards (%abc) prevent standard B-tree index traversal from finding matching string prefixes, forcing a full scan.",
                suggested_rewrite="Use trailing wildcard (col LIKE 'abc%'), full-text search (FTS5 in SQLite / tsvector in PG), or trigram indexes.",
                category="Index Utilization",
            ))

        # 7. Unnecessary DISTINCT
        if re.search(r"\bselect\s+distinct\b", q_clean, re.IGNORECASE):
            # Check if primary key or unique id is in select
            has_id = bool(re.search(r"\b\w*id\b", q_clean, re.IGNORECASE))
            findings.append(AntiPattern(
                pattern_name="Unnecessary DISTINCT Clause",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="DISTINCT forces an expensive deduplication sort or temporary hash table over the entire intermediate result set.",
                suggested_rewrite="Eliminate redundant 1-to-many duplicates via proper JOIN predicates or EXISTS semi-joins instead of masking them with DISTINCT.",
                category="Memory & Sorting",
            ))

        # 8. Unnecessary / Redundant GROUP BY
        if re.search(r"\bgroup\s+by\b", q_clean, re.IGNORECASE) and not re.search(r"\b(count|sum|avg|min|max|group_concat)\s*\(", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="GROUP BY Without Aggregates",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="Using GROUP BY purely for deduplication without aggregate functions is slower than targeted EXISTS filtering.",
                suggested_rewrite="Review query semantics: use targeted filtering or explicit DISTINCT if unique row projection is strictly intended.",
                category="Aggregation",
            ))

        # 9. ORDER BY without LIMIT
        if re.search(r"\border\s+by\b", q_clean, re.IGNORECASE) and not re.search(r"\blimit\s+\d+", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="ORDER BY Without LIMIT",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="Sorting an unbounded result set forces SQLite/Postgres to sort every single row in memory or spill to temporary disk b-trees.",
                suggested_rewrite="Append a sensible LIMIT clause (e.g. LIMIT 50) to allow the optimizer to employ a Top-N heap sort.",
                category="Sorting",
            ))

        # 10. Repeated Subqueries
        subquery_matches = re.findall(r"\(\s*select\s+[^)]+?\)", q_clean, re.IGNORECASE)
        if len(subquery_matches) >= 2 and len(subquery_matches) != len(set(subquery_matches)):
            findings.append(AntiPattern(
                pattern_name="Repeated Duplicate Subqueries",
                severity="HIGH",
                estimated_impact="High",
                why="Multiple identical subqueries repeat execution, calculating the exact same dataset multiple times.",
                suggested_rewrite="Extract the repeated subquery into a Common Table Expression (WITH cte AS (...)) and reuse it.",
                category="Query Structure",
            ))

        # 11. Correlated Subquery
        if re.search(r"\(\s*select\s+[^)]+?\bwhere\s+[\w.]+\s*=\s*[\w.]+", q_clean, re.IGNORECASE) and len(re.findall(r"\bfrom\b", q_clean, re.IGNORECASE)) > 1:
            findings.append(AntiPattern(
                pattern_name="Correlated Subquery in Projection/Filter",
                severity="CRITICAL",
                estimated_impact="High",
                why="Executes subquery repeatedly for every single outer row processed (quadratic O(N*M) runtime).",
                suggested_rewrite="Convert the correlated subquery into a standard LEFT JOIN or an aggregated CTE.",
                category="Complexity",
            ))

        # 12. Implicit Type Conversions in Predicates
        if re.search(r"[\w.]+\s*=\s*['\"]\d+['\"]", q_clean) and re.search(r"\b(id|count|amount|qty|quantity)\b", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="Implicit Type Conversion in Predicates",
                severity="LOW",
                estimated_impact="Low",
                why="Comparing numeric database columns with quoted string literals can force type casting on every row, evading indexes.",
                suggested_rewrite="Provide numeric literals directly without string quotes (e.g. WHERE user_id = 42 instead of '42').",
                category="SARGability",
            ))

        # 13. Cartesian Joins / Missing ON
        if re.search(r"\bcross\s+join\b", q_clean, re.IGNORECASE) or (len(re.findall(r"\bfrom\s+[\w]+(?:\s*,\s*[\w]+)+", q_clean, re.IGNORECASE)) > 0 and "where" not in q_lower):
            findings.append(AntiPattern(
                pattern_name="Cartesian Product / CROSS JOIN",
                severity="CRITICAL",
                estimated_impact="High",
                why="Produces N x M rows where every row in the first table pairs with every row in the second table, exploding memory and CPU.",
                suggested_rewrite="Add an explicit INNER JOIN with an ON clause specifying join keys.",
                category="Join Efficiency",
            ))

        # 14. Missing JOIN Predicate
        joins = re.findall(r"\b(inner|left|right|full)?\s*join\s+([\w]+)\s+([\w]+)?(?!\s+on\b|\s+using\b)", q_clean, re.IGNORECASE)
        # Verify if any join lacks ON or USING
        has_bare_join = bool(re.search(r"\bjoin\s+[\w]+(?:\s+as\s+[\w]+|\s+[\w]+)?\s+(?!on\b|using\b|join\b|where\b)", q_clean, re.IGNORECASE))
        if joins and has_bare_join:
            findings.append(AntiPattern(
                pattern_name="Missing JOIN ON / USING Predicate",
                severity="CRITICAL",
                estimated_impact="High",
                why="Joining tables without an explicit ON condition creates an accidental full Cartesian cross product.",
                suggested_rewrite="Specify the join key relationship using ON table1.key = table2.key.",
                category="Join Efficiency",
            ))

        # 15. HAVING Used Instead of WHERE
        if re.search(r"\bhaving\b[^\;]+?\b(status|date|created|type|id|name)\b", q_clean, re.IGNORECASE) and not re.search(r"\bhaving\s+[\w.]*\(", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="HAVING Used for Non-Aggregate Filtering",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="HAVING filters rows AFTER aggregation has processed every group. Filtering non-aggregates here wastes CPU.",
                suggested_rewrite="Move non-aggregate conditions into the WHERE clause so rows are pruned before grouping.",
                category="Aggregation",
            ))

        # 16. Redundant JOINs
        joined_tables = re.findall(r"\bjoin\s+([\w]+)\s+([\w]+)", q_clean, re.IGNORECASE)
        for tbl, alias in joined_tables:
            alias_use_count = len(re.findall(rf"\b{alias}\.[\w]+", q_clean, re.IGNORECASE))
            # If alias is only mentioned in the ON clause (1 occurrence) and not in SELECT or WHERE
            if alias_use_count <= 1:
                findings.append(AntiPattern(
                    pattern_name=f"Potentially Redundant JOIN on '{tbl}'",
                    severity="LOW",
                    estimated_impact="Low",
                    why=f"Table '{tbl}' (alias '{alias}') is joined but its columns are never referenced in projections or filters.",
                    suggested_rewrite="Remove the join unless it is strictly intended for existence filtering, in which case use EXISTS.",
                    category="Query Structure",
                ))
                break

        # 17. Unused Columns in Subqueries / CTEs
        if re.search(r"\bwith\s+[\w]+\s+as\s*\(\s*select\s+\*", q_clean, re.IGNORECASE) or re.search(r"\(\s*select\s+\*\s+from\s+[\w]+\s*\)\s+as", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="SELECT * in Subquery / CTE Definition",
                severity="MEDIUM",
                estimated_impact="Medium",
                why="Projecting all columns inside derived tables consumes memory buffers and prevents optimizer pushdown optimizations.",
                suggested_rewrite="Limit subquery columns to strictly those needed by the parent query.",
                category="I/O & Memory",
            ))

        # 18. Redundant Nested SELECTs
        if re.search(r"\bfrom\s*\(\s*select\s+[\w*,\s]+\s+from\s+[\w]+(?:\s+where\s+[^)]+)?\s*\)\s*(?:as\s+\w+)?\s*(?:$|;|\))", q_clean, re.IGNORECASE):
            findings.append(AntiPattern(
                pattern_name="Redundant Nested SELECT Wrapper",
                severity="LOW",
                estimated_impact="Low",
                why="Wrapping a simple SELECT inside an outer SELECT * without transformations adds syntax noise and wrapper overhead.",
                suggested_rewrite="Flatten the query into a single direct SELECT statement.",
                category="Query Cleanliness",
            ))

        # Plan-level scan detection
        if "scan" in plan_text.lower():
            already_scanned = any(f.pattern_name.startswith("Full table scan") for f in findings)
            if not already_scanned:
                findings.append(AntiPattern(
                    pattern_name="Full Table Scan Detected in Execution Plan",
                    severity="CRITICAL",
                    estimated_impact="High",
                    why="SQLite or database engine must inspect every row sequentially because no suitable B-Tree index exists.",
                    suggested_rewrite="Create a composite B-Tree index matching WHERE equality and range predicates.",
                    category="Execution Plan",
                ))

        return findings

    def analyze_complexity(self, query: str) -> QueryComplexity:
        q_lower = query.lower()

        joins = len(re.findall(r"\b(inner|left|right|full|cross)?\s*join\b", q_lower))
        subqueries = len(re.findall(r"\(\s*select\b", q_lower))
        aggregations = len(re.findall(r"\b(count|sum|avg|min|max|group_concat)\s*\(", q_lower))
        sorts = len(re.findall(r"\border\s+by\b", q_lower))
        filters = len(re.findall(r"\b(where|and|or)\b", q_lower))

        # Complexity risk score
        score = (joins * 20) + (subqueries * 25) + (aggregations * 15) + (sorts * 15) + (filters * 5)

        if score >= 60 or joins >= 3 or subqueries >= 2:
            risk = "HIGH"
        elif score >= 30 or joins >= 1 or aggregations >= 1 or sorts >= 1:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        # Dominant cost factor
        if subqueries >= 2 or (subqueries >= 1 and joins >= 1):
            dominant = "Nested Subquery Execution & Materialization"
            explanation = f"Query contains {subqueries} subquery levels and {joins} table joins. Multiple subqueries force row materialization and risk nested-loop scans."
        elif joins >= 2:
            dominant = "Multi-Table Join Graph"
            explanation = f"Query executes joins across {joins + 1} tables. Without matching index paths on foreign keys, join processing will scale exponentially."
        elif sorts >= 1 and "limit" not in q_lower:
            dominant = "Unbounded Sort Buffer (ORDER BY)"
            explanation = "Unbounded sorting forces temporary B-Tree structures or disk sorting before returning the first result row."
        elif aggregations >= 1:
            dominant = "Aggregate Group Hash / Sort"
            explanation = f"Query requires {aggregations} aggregate calculations over grouped records, requiring intermediate hashing or grouping buffers."
        else:
            dominant = "Linear Table Scan"
            explanation = f"Query has {filters} filter conditions. Ensuring indexes exist on filtered columns is the primary optimization lever."

        return QueryComplexity(
            join_count=joins,
            subquery_count=subqueries,
            aggregation_count=aggregations,
            sort_count=sorts,
            filter_count=filters,
            risk_level=risk,
            dominant_cost_factor=dominant,
            explanation=explanation,
        )
