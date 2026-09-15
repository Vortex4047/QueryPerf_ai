import unittest
from main import battle_arena, cliff_detector_endpoint, optimize
from services.learned_optimizer import LearnedOptimizerService
from services.performance_predictor import PerformancePredictorService
from services.root_cause_service import RootCauseService
from services.battle_service import BattleArenaService
from services.experiment_service import ScientificExperimentService
from services.cliff_detector import PerformanceCliffService
from services.explainer_service import ExplainerService
from services.decision_tree_service import DecisionTreeService
from schemas import BattleRequest, CliffDetectorRequest, OptimizationRequest, EngineType

SAMPLE_DDL = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
"""

SAMPLE_QUERY = "SELECT * FROM orders WHERE customer_id = 42 AND status = 'DELIVERED';"


class TestAdvancedIntelligence(unittest.TestCase):
    def test_learned_optimizer(self):
        result = LearnedOptimizerService.analyze_and_learn(
            SAMPLE_QUERY, "SCAN TABLE orders", measured_speedup=82.5
        )
        self.assertIsNotNone(result)
        self.assertIn("orders", result.query_signature)
        self.assertGreater(result.historical_speedup_avg, 0)
        self.assertGreater(result.precedent_count, 0)

    def test_performance_predictor(self):
        pred = PerformancePredictorService.predict(
            SAMPLE_QUERY, SAMPLE_DDL, actual_ms=0.45
        )
        self.assertIsNotNone(pred)
        self.assertGreater(pred.predicted_rows, 0)
        self.assertGreater(pred.accuracy_percent, 70.0)
        self.assertIn(pred.risk_level, ["LOW", "MEDIUM", "HIGH"])

    def test_root_cause_service(self):
        tree = RootCauseService.diagnose(
            SAMPLE_QUERY, "SCAN TABLE orders", [], []
        )
        self.assertEqual(tree.level, 1)
        self.assertEqual(len(tree.children), 1)
        self.assertEqual(tree.children[0].level, 2)
        self.assertEqual(tree.children[0].children[0].level, 3)

    def test_battle_arena(self):
        req = BattleRequest(
            ddl_schema=SAMPLE_DDL,
            original_query=SAMPLE_QUERY,
            human_query="SELECT order_id, total_amount FROM orders WHERE customer_id = 42 LIMIT 10;",
        )
        res = BattleArenaService.execute_tournament(req)
        self.assertIsNotNone(res.winner_name)
        self.assertGreaterEqual(len(res.participants), 3)
        self.assertTrue(any(p.is_winner for p in res.participants))

    def test_battle_endpoint(self):
        req = BattleRequest(
            ddl_schema=SAMPLE_DDL,
            original_query=SAMPLE_QUERY,
            human_query="SELECT order_id FROM orders WHERE customer_id = 42;",
        )
        data = battle_arena(req)
        self.assertIsNotNone(data.participants)
        self.assertIsNotNone(data.winner_name)

    def test_scientific_experiment(self):
        exp = ScientificExperimentService.run_experiment(
            SAMPLE_QUERY, SAMPLE_DDL, iterations=10
        )
        self.assertIsNotNone(exp)
        self.assertGreater(exp.iterations, 0)
        self.assertIn("p <", exp.p_value_text)

    def test_cliff_detector(self):
        cliff = PerformanceCliffService.detect_cliff(SAMPLE_QUERY, SAMPLE_DDL)
        self.assertIsNotNone(cliff)
        self.assertEqual(len(cliff.data_points), 4)
        self.assertIn(cliff.curve_type, ["linear", "quadratic", "logarithmic"])

    def test_cliff_endpoint(self):
        req = CliffDetectorRequest(ddl_schema=SAMPLE_DDL, query=SAMPLE_QUERY)
        data = cliff_detector_endpoint(req)
        self.assertIn(data.curve_type, ["linear", "quadratic", "logarithmic"])
        self.assertEqual(len(data.data_points), 4)

    def test_explainer_service(self):
        steps = ExplainerService.generate_dual_explanation(
            SAMPLE_QUERY, "SCAN TABLE orders"
        )
        self.assertGreaterEqual(len(steps), 4)
        self.assertTrue(all(s.beginner_analogy for s in steps))
        self.assertTrue(all(s.dba_technical_insight for s in steps))

    def test_decision_tree_service(self):
        tree = DecisionTreeService.build_tree(
            SAMPLE_QUERY, "SCAN TABLE orders", True
        )
        self.assertGreaterEqual(len(tree), 4)
        self.assertTrue(all(n.question for n in tree))

    def test_optimize_endpoint_includes_new_intelligence(self):
        req = OptimizationRequest(ddl_schema=SAMPLE_DDL, slow_query=SAMPLE_QUERY, engine=EngineType.SQLITE)
        res = optimize(req)
        self.assertIsNotNone(res.performance_prediction)
        self.assertIsNotNone(res.learned_optimization)
        self.assertIsNotNone(res.root_cause_tree)
        self.assertIsNotNone(res.scientific_experiment)
        self.assertIsNotNone(res.performance_cliff)
        self.assertGreater(len(res.plan_heatmap), 0)
        self.assertGreater(len(res.dual_persona_explainer), 0)
        self.assertGreater(len(res.decision_tree), 0)

    def test_explainer_service(self):
        steps = ExplainerService.generate_dual_explanation(
            SAMPLE_QUERY, "SCAN TABLE orders"
        )
        self.assertGreaterEqual(len(steps), 4)
        self.assertTrue(all(s.beginner_analogy for s in steps))
        self.assertTrue(all(s.dba_technical_insight for s in steps))

    def test_decision_tree_service(self):
        tree = DecisionTreeService.build_tree(
            SAMPLE_QUERY, "SCAN TABLE orders", True
        )
        self.assertGreaterEqual(len(tree), 4)
        self.assertTrue(all(n.question for n in tree))


if __name__ == "__main__":
    unittest.main()
