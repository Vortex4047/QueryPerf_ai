import unittest
from services.db_service import DatabaseSandboxService
from services.rewrite_engine import QueryRewriteEngine


class TestDatabaseSandbox(unittest.TestCase):
    def setUp(self):
        self.sandbox = DatabaseSandboxService()
        self.ddl = """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, email TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date DATE, total_amount REAL, status TEXT);
        """
        self.query = "SELECT * FROM orders WHERE status = 'DELIVERED' AND order_date >= '2025-01-01';"

    def test_sandbox_pipeline_execution(self):
        result = self.sandbox.execute_sandbox_pipeline(
            self.ddl,
            self.query,
            "SELECT order_id, customer_id, total_amount FROM orders WHERE status = 'DELIVERED';",
            ["CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);"]
        )
        self.assertGreater(result.original_ms, 0)
        self.assertGreater(result.optimized_ms, 0)
        self.assertTrue(len(result.what_if_indexes) > 0)
        self.assertIn("idx_orders_status", result.what_if_indexes[0]["index_command"])

    def test_what_if_index_simulation(self):
        res = self.sandbox.simulate_custom_index(
            self.ddl,
            self.query,
            "CREATE INDEX idx_orders_status_date ON orders(status, order_date);"
        )
        self.assertTrue(res.valid)
        self.assertIn(res.verdict, ["Useful", "Neutral", "Redundant"])
        self.assertGreater(res.before_ms, 0)
        self.assertGreater(res.after_ms, 0)

    def test_benchmark_distribution(self):
        dist = self.sandbox.benchmark_distribution(self.ddl, self.query, iterations=10)
        self.assertEqual(dist.iterations, 10)
        self.assertEqual(len(dist.samples), 10)
        self.assertGreaterEqual(dist.max_ms, dist.min_ms)
        self.assertEqual(len(dist.distribution_buckets), 5)

    def test_rewrite_candidates_generation(self):
        engine = QueryRewriteEngine()
        candidates = engine.generate_candidates("SELECT * FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE strftime('%Y', o.order_date) = '2025';")
        self.assertEqual(len(candidates), 3)
        self.assertIn("rewrite_1", [c["id"] for c in candidates])


if __name__ == "__main__":
    unittest.main()
