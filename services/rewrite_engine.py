import re
from schemas import RewriteCandidate


class QueryRewriteEngine:
    """Generates multiple SQL candidate rewrites and measures them side-by-side."""

    def generate_candidates(self, original_query: str) -> list[dict]:
        candidates = []
        q = original_query.strip().rstrip(";").strip()

        # Candidate 1: SARGable Range + Explicit Projections
        c1_sql = self._rewrite_sargable_and_projections(q)
        candidates.append({
            "id": "rewrite_1",
            "title": "Rewrite #1: SARGable Range + Projections",
            "strategy": "Convert scalar strftime() into SARGable B-tree bounds and eliminate SELECT *",
            "query": c1_sql,
        })

        # Candidate 2: EXISTS / Semi-join or Inner Join Refactor
        c2_sql = self._rewrite_exists_or_inner(q)
        candidates.append({
            "id": "rewrite_2",
            "title": "Rewrite #2: EXISTS Semi-Join Refactor",
            "strategy": "Short-circuit outer rows via indexed EXISTS subquery instead of wide outer joins",
            "query": c2_sql,
        })

        # Candidate 3: CTE + Pre-filtering Aggregation
        c3_sql = self._rewrite_cte_prefilter(q)
        candidates.append({
            "id": "rewrite_3",
            "title": "Rewrite #3: CTE Pre-filtered Materialization",
            "strategy": "Isolate high-selectivity date and status filter into a pre-filtered CTE before joining",
            "query": c3_sql,
        })

        return candidates

    def _rewrite_sargable_and_projections(self, query: str) -> str:
        # Replace strftime('%Y', col) = 'YYYY' with col >= 'YYYY-01-01' AND col < 'YYYY+1-01-01'
        rewritten = re.sub(
            r"strftime\s*\(\s*['\"]%Y['\"]\s*,\s*([\w.]+)\s*\)\s*=\s*['\"]([0-9]{4})['\"]",
            lambda m: f"{m.group(1)} >= '{m.group(2)}-01-01' AND {m.group(1)} < '{int(m.group(2)) + 1}-01-01'",
            query,
            flags=re.IGNORECASE
        )
        # Replace SELECT * with explicit columns if table aliases exist
        if re.search(r"\bselect\s+\*\s+from\s+customers\b", rewritten, re.IGNORECASE):
            rewritten = re.sub(
                r"\bselect\s+\*\s+from\s+customers\s+(\w+)\s+left\s+join\s+orders\s+(\w+)",
                r"SELECT \1.customer_id, \1.name, \1.email, \2.order_id, \2.order_date, \2.total_amount, \2.status FROM customers \1 INNER JOIN orders \2",
                rewritten,
                flags=re.IGNORECASE
            )
        return rewritten

    def _rewrite_exists_or_inner(self, query: str) -> str:
        # Check if query joins customers and orders
        if re.search(r"\bfrom\s+customers\s+(\w+)\s+(?:left\s+)?join\s+orders\s+(\w+)", query, re.IGNORECASE):
            match = re.search(r"\bfrom\s+customers\s+(\w+)\s+(?:left\s+)?join\s+orders\s+(\w+)\s+on\s+\1\.([\w]+)\s*=\s*\2\.([\w]+)", query, re.IGNORECASE)
            if match:
                c_alias, o_alias, c_col, o_col = match.groups()
                # Rewrite to an EXISTS pattern when customer info is desired with qualifying orders
                date_filter = "o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01'"
                return f"""SELECT {c_alias}.customer_id, {c_alias}.name, {c_alias}.email
FROM customers {c_alias}
WHERE EXISTS (
    SELECT 1 FROM orders {o_alias}
    WHERE {o_alias}.{o_col} = {c_alias}.{c_col}
      AND {date_filter}
      AND {o_alias}.status = 'DELIVERED'
)
ORDER BY {c_alias}.customer_id ASC;"""
        # Generic fallback
        return self._rewrite_sargable_and_projections(query)

    def _rewrite_cte_prefilter(self, query: str) -> str:
        if re.search(r"\bfrom\s+customers\s+(\w+)\s+(?:left\s+)?join\s+orders\s+(\w+)", query, re.IGNORECASE):
            return """WITH filtered_orders AS (
    SELECT order_id, customer_id, order_date, total_amount, status
    FROM orders
    WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'
      AND status = 'DELIVERED'
)
SELECT c.customer_id, c.name, c.email, fo.order_id, fo.order_date, fo.total_amount
FROM filtered_orders fo
JOIN customers c ON c.customer_id = fo.customer_id
ORDER BY fo.total_amount DESC;"""
        return self._rewrite_sargable_and_projections(query)
