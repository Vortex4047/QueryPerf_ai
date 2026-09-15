import re
from schemas import VisualPlanNode


class PlanVisualizerService:
    """Transforms raw textual EXPLAIN QUERY PLAN and execution statistics into an interactive node tree."""

    def parse_sqlite_plan(self, plan_text: str, query_type: str = "SELECT") -> VisualPlanNode:
        lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
        if not lines or "no plan steps" in plan_text.lower():
            return VisualPlanNode(
                id="root_1",
                name="RESULT SET",
                operation_type="result",
                cost_level="optimal",
                detail="Empty or trivial execution plan",
                explanation="SQLite returned an empty or instant constant plan.",
                children=[]
            )

        # Parse lines formatted as: [id:parent] detail
        raw_nodes = []
        for index, line in enumerate(lines):
            match = re.match(r"^\[(\d+):(\d+)\]\s*(.*)$", line)
            if match:
                node_id, parent_id, detail = match.groups()
                raw_nodes.append({
                    "id": node_id,
                    "parent_id": parent_id,
                    "detail": detail,
                    "original_line": line
                })
            else:
                raw_nodes.append({
                    "id": str(index + 1),
                    "parent_id": "0",
                    "detail": line,
                    "original_line": line
                })

        # Convert to VisualPlanNode
        def build_node(item: dict) -> VisualPlanNode:
            detail = item["detail"]
            op_type, cost_level, name, table, idx, explanation = self._classify_sqlite_step(detail)
            return VisualPlanNode(
                id=f"node_{item['id']}",
                name=name,
                operation_type=op_type,
                cost_level=cost_level,
                detail=detail,
                table=table,
                index_name=idx,
                rows_est=1200 if op_type == "scan" else 24,
                explanation=explanation,
                children=[]
            )

        # Build tree hierarchy
        node_map = {n["id"]: build_node(n) for n in raw_nodes}
        root_nodes = []

        for item in raw_nodes:
            parent_id = item["parent_id"]
            current_node = node_map[item["id"]]
            if parent_id in node_map and parent_id != item["id"] and parent_id != "0":
                node_map[parent_id].children.append(current_node)
            else:
                root_nodes.append(current_node)

        # Create master root node
        master_root = VisualPlanNode(
            id="plan_root",
            name=query_type.upper(),
            operation_type="result",
            cost_level="optimal" if not any("scan" in l.lower() for l in lines) else "critical",
            detail=f"{query_type} Query Execution Pipeline",
            explanation="Top-level output coordinator receiving rows from lower query plan operators.",
            children=root_nodes if root_nodes else list(node_map.values())
        )
        return master_root

    def _classify_sqlite_step(self, detail: str) -> tuple[str, str, str, str, str, str]:
        """Returns: (operation_type, cost_level, name, table, index_name, explanation)"""
        d_lower = detail.lower()

        # SCAN operation
        if "scan" in d_lower:
            table_match = re.search(r"scan\s+([\w]+)", detail, re.I)
            table = table_match.group(1) if table_match else "table"
            return (
                "scan",
                "critical",
                f"SCAN {table}",
                table,
                "",
                f"SQLite is sequentially scanning every single row in '{table}' because no suitable index exists on the filter/join columns. This creates high disk/memory I/O overhead."
            )

        # SEARCH USING INDEX
        if "search" in d_lower and ("using index" in d_lower or "using covering index" in d_lower):
            table_match = re.search(r"search\s+([\w]+)", detail, re.I)
            idx_match = re.search(r"using (?:covering )?index\s+([\w]+)", detail, re.I)
            table = table_match.group(1) if table_match else "table"
            idx = idx_match.group(1) if idx_match else "index"
            return (
                "search",
                "optimal",
                f"INDEX SEEK ({idx})",
                table,
                idx,
                f"SQLite is traversing B-Tree index '{idx}' on table '{table}' to seek directly to matching entries. Highly efficient logarithmic lookup."
            )

        # SEARCH USING PRIMARY KEY
        if "search" in d_lower and "primary key" in d_lower:
            table_match = re.search(r"search\s+([\w]+)", detail, re.I)
            table = table_match.group(1) if table_match else "table"
            return (
                "search",
                "optimal",
                f"PRIMARY KEY SEEK ({table})",
                table,
                "PRIMARY KEY",
                f"Direct integer primary key lookup on '{table}'. Constant-time to logarithmic seek."
            )

        # TEMP B-TREE
        if "temp b-tree" in d_lower:
            return (
                "temp_btree",
                "warning",
                "TEMP B-TREE",
                "",
                "",
                "SQLite created an ephemeral in-memory or disk B-Tree structure to process an ORDER BY, DISTINCT, or GROUP BY operation."
            )

        # SORT
        if "sort" in d_lower or "order by" in d_lower:
            return (
                "sort",
                "warning",
                "SORT ROWS",
                "",
                "",
                "SQLite is sorting candidate rows in memory. Without an index covering the sort columns, all rows must be buffered before delivery."
            )

        # COMPOUND / SUBQUERY
        if "compound subqueries" in d_lower or "subquery" in d_lower:
            return (
                "join",
                "warning",
                "SUBQUERY CO-ROUTINE",
                "",
                "",
                "SQLite is executing a subquery co-routine to generate intermediate rows for the outer query."
            )

        # Default fallback
        return (
            "filter",
            "neutral",
            detail.split()[0].upper() if detail else "OPERATOR",
            "",
            "",
            detail
        )

    def parse_postgres_plan(self, plan_text: str) -> VisualPlanNode:
        """Parses PostgreSQL EXPLAIN (ANALYZE, BUFFERS) textual output into a node tree."""
        lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
        root = VisualPlanNode(
            id="pg_root",
            name="PG QUERY PLAN",
            operation_type="result",
            cost_level="optimal",
            detail="PostgreSQL Execution Pipeline",
            explanation="PostgreSQL Cost-Based Optimizer physical execution tree.",
            children=[]
        )

        for i, line in enumerate(lines):
            l_lower = line.lower()
            if "seq scan" in l_lower:
                tbl = re.search(r"on\s+([\w]+)", line, re.I)
                table = tbl.group(1) if tbl else "table"
                root.children.append(VisualPlanNode(
                    id=f"pg_node_{i}",
                    name=f"Seq Scan on {table}",
                    operation_type="scan",
                    cost_level="critical",
                    detail=line,
                    table=table,
                    explanation=f"Sequential Scan on '{table}'. PostgreSQL reads all table heap pages sequentially.",
                    children=[]
                ))
            elif "index scan" in l_lower or "bitmap index scan" in l_lower:
                idx = re.search(r"using\s+([\w]+)", line, re.I)
                index_name = idx.group(1) if idx else "idx"
                root.children.append(VisualPlanNode(
                    id=f"pg_node_{i}",
                    name=f"Index Scan ({index_name})",
                    operation_type="search",
                    cost_level="optimal",
                    detail=line,
                    index_name=index_name,
                    explanation=f"B-Tree index seek traversing '{index_name}' directly to qualified heap tuples.",
                    children=[]
                ))
            elif "hash join" in l_lower or "merge join" in l_lower or "nested loop" in l_lower:
                join_type = "Hash Join" if "hash" in l_lower else ("Merge Join" if "merge" in l_lower else "Nested Loop")
                root.children.append(VisualPlanNode(
                    id=f"pg_node_{i}",
                    name=join_type,
                    operation_type="join",
                    cost_level="warning" if "nested" in l_lower else "optimal",
                    detail=line,
                    explanation=f"PostgreSQL {join_type} combining rows from inner and outer relation buffers.",
                    children=[]
                ))
        return root

    def parse_mysql_plan(self, plan_text: str) -> VisualPlanNode:
        """Parses MySQL EXPLAIN ANALYZE textual output into a node tree."""
        lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
        root = VisualPlanNode(
            id="mysql_root",
            name="MYSQL QUERY PLAN",
            operation_type="result",
            cost_level="optimal",
            detail="MySQL Execution Pipeline",
            explanation="MySQL InnoDB Iterator Plan.",
            children=[]
        )
        for i, line in enumerate(lines):
            l_lower = line.lower()
            if "table scan" in l_lower or "all" in l_lower:
                tbl = re.search(r"on\s+([\w]+)", line, re.I)
                table = tbl.group(1) if tbl else "table"
                root.children.append(VisualPlanNode(
                    id=f"my_node_{i}",
                    name=f"Table Scan ({table})",
                    operation_type="scan",
                    cost_level="critical",
                    detail=line,
                    table=table,
                    explanation=f"MySQL InnoDB Full Table Scan on '{table}'. Inspects every clustered index leaf.",
                    children=[]
                ))
            elif "index lookup" in l_lower or "index scan" in l_lower or "ref" in l_lower:
                root.children.append(VisualPlanNode(
                    id=f"my_node_{i}",
                    name="Index Lookup",
                    operation_type="search",
                    cost_level="optimal",
                    detail=line,
                    explanation="MySQL indexed seek finding matching rows using B-Tree index structure.",
                    children=[]
                ))
        return root
