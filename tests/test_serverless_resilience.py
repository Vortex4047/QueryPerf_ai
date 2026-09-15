import os
import tempfile
import unittest
from unittest.mock import patch
from main import optimize, dashboard
from schemas import EngineType, OptimizationRequest
from services.db_storage import get_storage_db_path
from services.history_service import QueryHistoryService
from services.learned_optimizer import LearnedOptimizerService


class TestServerlessResilience(unittest.TestCase):
    def test_db_path_on_vercel_env(self):
        with patch.dict(os.environ, {"VERCEL": "1"}):
            path = get_storage_db_path("test.sqlite")
            self.assertTrue(path.startswith(tempfile.gettempdir()))

    def test_db_path_on_aws_lambda_env(self):
        with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "queryperf-api"}):
            path = get_storage_db_path("test.sqlite")
            self.assertTrue(path.startswith(tempfile.gettempdir()))

    def test_custom_db_path_override(self):
        with patch.dict(os.environ, {"QUERYPERF_DB_PATH": "/tmp/custom.sqlite"}):
            path = get_storage_db_path("test.sqlite")
            self.assertEqual(path, "/tmp/custom.sqlite")

    def test_history_service_resilience_on_sqlite_failure(self):
        # Force invalid path to simulate read-only / forbidden directory
        with patch.object(QueryHistoryService, "__init__", lambda self: setattr(self, "path", "/proc/invalid/read_only.sqlite")):
            service = QueryHistoryService()
            fp, alert = service.record("SELECT * FROM users;", 10, "1.5x Faster", 33.0)
            self.assertTrue(len(fp) > 0)
            self.assertFalse(alert.is_regression)
            self.assertEqual(service.list(), [])
            stats = service.get_dashboard_stats()
            self.assertIsNotNone(stats)

    def test_learned_optimizer_resilience_on_sqlite_failure(self):
        with patch.object(LearnedOptimizerService, "get_db_path", return_value="/proc/invalid/read_only.sqlite"):
            opt = LearnedOptimizerService.analyze_and_learn("SELECT * FROM orders WHERE customer_id = 1", "SCAN TABLE orders")
            self.assertIsNotNone(opt)
            self.assertGreater(opt.historical_speedup_avg, 0)
            self.assertGreater(opt.confidence_score, 0)

    def test_full_analysis_in_vercel_mode(self):
        with patch.dict(os.environ, {"VERCEL": "1"}):
            ddl = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);"
            query = "SELECT * FROM users WHERE name = 'Alice';"
            req = OptimizationRequest(ddl_schema=ddl, slow_query=query, engine=EngineType.SQLITE)
            res = optimize(req)
            self.assertIsNotNone(res.visual_plan_original)
            self.assertIsNotNone(res.learned_optimization)

    def test_db_path_on_vercel_env_variants(self):
        for key in ["VERCEL_ENV", "VERCEL_URL", "VERCEL_REGION", "NOW_REGION"]:
            with patch.dict(os.environ, {key: "test_val"}, clear=True):
                path = get_storage_db_path("test.sqlite")
                self.assertTrue(path.startswith(tempfile.gettempdir()))

    def test_ecommerce_scenario_in_vercel_mode(self):
        """Tests the exact eCommerce scenario from Scenario 1 under simulated Vercel serverless environment."""
        with patch.dict(os.environ, {"VERCEL": "1", "VERCEL_ENV": "production"}):
            schema = """CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                created_at DATETIME
            );

            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date DATE NOT NULL,
                total_amount DECIMAL(10,2),
                status TEXT
            );"""
            query = """SELECT * FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE strftime('%Y', o.order_date) = '2025' AND o.status LIKE '%DELIVERED%' ORDER BY o.total_amount DESC;"""
            req = OptimizationRequest(ddl_schema=schema, slow_query=query, engine=EngineType.SQLITE)
            res = optimize(req)
            self.assertIsNotNone(res)
            self.assertIsNotNone(res.visual_plan_original)
            self.assertGreater(len(res.what_if_indexes), 0)
            self.assertIsNotNone(res.scientific_experiment)
            self.assertIsNotNone(res.performance_cliff)


if __name__ == "__main__":
    unittest.main()
