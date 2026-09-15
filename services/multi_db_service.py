import re
from schemas import EngineType, VisualPlanNode
from services.plan_visualizer import PlanVisualizerService


class MultiDatabaseService:
    """Provides dialect translation, execution plan simulation, and engine-specific insights for SQLite, PostgreSQL, and MySQL."""

    def __init__(self):
        self.visualizer = PlanVisualizerService()

    def generate_dialect_plan(self, engine: EngineType, query: str, has_index: bool = False) -> tuple[str, VisualPlanNode]:
        if engine == EngineType.POSTGRES:
            return self._generate_postgres_plan(query, has_index)
        elif engine == EngineType.MYSQL:
            return self._generate_mysql_plan(query, has_index)
        else:
            raise ValueError("SQLite plans are generated directly via the live sandbox.")

    def _generate_postgres_plan(self, query: str, has_index: bool) -> tuple[str, VisualPlanNode]:
        if has_index:
            plan_text = """Hash Join  (cost=12.45..48.20 rows=24 width=142) (actual time=0.084..0.312 rows=18 loops=1)
  Hash Cond: (o.customer_id = c.customer_id)
  Buffers: shared hit=42
  ->  Bitmap Heap Scan on orders o  (cost=4.25..32.10 rows=45 width=72) (actual time=0.041..0.125 rows=38 loops=1)
        Recheck Cond: ((order_date >= '2025-01-01'::date) AND (order_date < '2026-01-01'::date) AND (status = 'DELIVERED'::text))
        Buffers: shared hit=18
        ->  Bitmap Index Scan on idx_orders_customer_status  (cost=0.00..4.24 rows=45 width=0) (actual time=0.025..0.025 rows=38 loops=1)
              Index Cond: (status = 'DELIVERED'::text)
              Buffers: shared hit=6
  ->  Hash  (cost=6.50..6.50 rows=120 width=70) (actual time=0.035..0.035 rows=120 loops=1)
        Buckets: 1024  Batches: 1  Memory Usage: 16kB
        Buffers: shared hit=8
        ->  Seq Scan on customers c  (cost=0.00..6.50 rows=120 width=70) (actual time=0.008..0.021 rows=120 loops=1)
Planning Time: 0.245 ms
Execution Time: 0.385 ms"""
        else:
            plan_text = """Hash Join  (cost=38.50..128.40 rows=240 width=142) (actual time=1.840..6.420 rows=182 loops=1)
  Hash Cond: (o.customer_id = c.customer_id)
  Buffers: shared hit=128 read=14
  ->  Seq Scan on orders o  (cost=0.00..82.00 rows=400 width=72) (actual time=0.024..4.120 rows=400 loops=1)
        Filter: ((order_date >= '2025-01-01'::date) AND (status ~~ '%DELIVERED%'::text))
        Rows Removed by Filter: 800
        Buffers: shared hit=96 read=14
  ->  Hash  (cost=22.50..22.50 rows=1200 width=70) (actual time=0.480..0.480 rows=1200 loops=1)
        Buckets: 2048  Batches: 1  Memory Usage: 112kB
        Buffers: shared hit=32
        ->  Seq Scan on customers c  (cost=0.00..22.50 rows=1200 width=70) (actual time=0.012..0.290 rows=1200 loops=1)
Planning Time: 0.312 ms
Execution Time: 6.540 ms"""
        tree = self.visualizer.parse_postgres_plan(plan_text)
        return plan_text, tree

    def _generate_mysql_plan(self, query: str, has_index: bool) -> tuple[str, VisualPlanNode]:
        if has_index:
            plan_text = """-> Nested loop inner join  (cost=14.2 rows=24) (actual time=0.052..0.410 rows=18 loops=1)
    -> Index lookup on o using idx_orders_customer_status (status='DELIVERED')  (cost=5.1 rows=38) (actual time=0.028..0.142 rows=38 loops=1)
    -> Single-row index lookup on c using PRIMARY (customer_id=o.customer_id)  (cost=0.24 rows=1) (actual time=0.005..0.006 rows=1 loops=38)"""
        else:
            plan_text = """-> Nested loop inner join  (cost=284 rows=320) (actual time=0.310..8.450 rows=180 loops=1)
    -> Filter: ((o.status like '%DELIVERED%') and (o.order_date >= '2025-01-01'))  (cost=124 rows=320) (actual time=0.045..5.120 rows=380 loops=1)
        -> Table scan on orders o  (cost=124 rows=1200) (actual time=0.040..3.850 rows=1200 loops=1)
    -> Single-row index lookup on c using PRIMARY (customer_id=o.customer_id)  (cost=0.25 rows=1) (actual time=0.006..0.007 rows=1 loops=380)"""
        tree = self.visualizer.parse_mysql_plan(plan_text)
        return plan_text, tree
