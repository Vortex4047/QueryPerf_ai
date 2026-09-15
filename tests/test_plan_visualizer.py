import unittest
from services.plan_visualizer import PlanVisualizerService


class TestPlanVisualizer(unittest.TestCase):
    def setUp(self):
        self.visualizer = PlanVisualizerService()

    def test_sqlite_plan_parsing(self):
        plan_text = """[2:0] SCAN orders
[3:0] SEARCH customers USING INTEGER PRIMARY KEY (rowid=?)"""
        root = self.visualizer.parse_sqlite_plan(plan_text)
        self.assertEqual(root.name, "SELECT")
        self.assertEqual(len(root.children), 2)
        scan_node = root.children[0]
        self.assertEqual(scan_node.operation_type, "scan")
        self.assertEqual(scan_node.cost_level, "critical")
        self.assertEqual(scan_node.table, "orders")
        self.assertTrue("orders" in scan_node.explanation)

        search_node = root.children[1]
        self.assertEqual(search_node.operation_type, "search")
        self.assertEqual(search_node.cost_level, "optimal")

    def test_postgres_plan_parsing(self):
        plan_text = """Hash Join  (cost=12.45..48.20 rows=24 width=142)
  ->  Bitmap Heap Scan on orders o  (cost=4.25..32.10 rows=45 width=72)
        ->  Bitmap Index Scan on idx_orders_customer_status
  ->  Seq Scan on customers c"""
        root = self.visualizer.parse_postgres_plan(plan_text)
        self.assertEqual(root.id, "pg_root")
        self.assertGreaterEqual(len(root.children), 1)

    def test_mysql_plan_parsing(self):
        plan_text = """-> Nested loop inner join
    -> Index lookup on o using idx_orders_customer_status
    -> Single-row index lookup on c using PRIMARY"""
        root = self.visualizer.parse_mysql_plan(plan_text)
        self.assertEqual(root.id, "mysql_root")
        self.assertGreaterEqual(len(root.children), 1)


if __name__ == "__main__":
    unittest.main()
