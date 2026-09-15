import unittest
from main import (dashboard, health, natural_language_copilot, optimize,
                  schema_completions, what_if_simulator, benchmark_distribution)
from schemas import (BenchmarkDistributionRequest, EngineType,
                     NaturalLanguageRequest, OptimizationRequest,
                     WhatIfSimRequest)


class TestAPIHandlers(unittest.TestCase):
    def setUp(self):
        self.ddl = """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, email TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date DATE, total_amount REAL, status TEXT);
        """
        self.query = "SELECT * FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE strftime('%Y', o.order_date) = '2025' AND o.status LIKE '%DELIVERED%' ORDER BY o.total_amount DESC;"

    def test_health(self):
        res = health()
        self.assertEqual(res["status"], "ok")

    def test_dashboard(self):
        data = dashboard()
        self.assertGreaterEqual(data.total_queries_analyzed, 1)
        self.assertGreater(data.average_speedup_percent, 0)
        self.assertTrue(len(data.antipattern_distribution) > 0)

    def test_schema_completions(self):
        data = schema_completions(OptimizationRequest(ddl_schema=self.ddl, slow_query="SELECT 1;"))
        self.assertIn("customers", data.tables)
        self.assertIn("orders", data.tables)

    def test_optimize_endpoint(self):
        req = OptimizationRequest(ddl_schema=self.ddl, slow_query=self.query, engine=EngineType.SQLITE)
        res = optimize(req)
        self.assertGreater(res.original_ms, 0)
        self.assertGreater(res.optimized_ms, 0)
        self.assertIn("Faster", res.speedup_factor)
        self.assertIsNotNone(res.visual_plan_original)
        self.assertIsNotNone(res.visual_plan_optimized)
        self.assertTrue(len(res.rewrite_candidates) >= 1)
        self.assertTrue(len(res.index_advisor) >= 1)
        self.assertGreaterEqual(res.confidence_breakdown.score, 50)
        self.assertIn(res.complexity_analysis.risk_level, ["LOW", "MEDIUM", "HIGH"])

    def test_what_if_endpoint(self):
        req = WhatIfSimRequest(
            ddl_schema=self.ddl,
            query=self.query,
            index_command="CREATE INDEX idx_orders_status ON orders(status);",
            engine=EngineType.SQLITE,
        )
        res = what_if_simulator(req)
        self.assertTrue(res.valid)
        self.assertIn(res.verdict, ["Useful", "Neutral", "Redundant"])

    def test_nl_to_sql_endpoint(self):
        req = NaturalLanguageRequest(
            prompt="Find customers who placed more than 5 orders in 2025 and sort by total spending",
            ddl_schema=self.ddl,
            engine=EngineType.SQLITE,
        )
        res = natural_language_copilot(req)
        self.assertIn("SELECT", res.generated_sql.upper())
        self.assertGreater(res.confidence_score, 50)

    def test_benchmark_distribution_endpoint(self):
        req = BenchmarkDistributionRequest(
            ddl_schema=self.ddl,
            query="SELECT * FROM orders WHERE status = 'DELIVERED';",
            iterations=10,
        )
        res = benchmark_distribution(req)
        self.assertEqual(res.iterations, 10)
        self.assertEqual(len(res.distribution_buckets), 5)


if __name__ == "__main__":
    unittest.main()
