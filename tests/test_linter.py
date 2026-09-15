import unittest
from services.linter_service import SQLLinterService


class TestSQLLinter(unittest.TestCase):
    def setUp(self):
        self.linter = SQLLinterService()

    def test_select_star_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT * FROM customers;")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("SELECT *" in name for name in names))

    def test_or_in_where_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT id FROM orders WHERE status = 'PENDING' OR total_amount > 100;")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("OR Condition" in name for name in names))

    def test_not_in_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT id FROM customers WHERE id NOT IN (SELECT customer_id FROM orders);")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("NOT IN" in name for name in names))

    def test_non_sargable_function_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT id FROM orders WHERE strftime('%Y', order_date) = '2025';")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("Function / Expression" in name for name in names))

    def test_leading_wildcard_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT id FROM customers WHERE email LIKE '%@gmail.com';")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("Leading Wildcard" in name for name in names))

    def test_unnecessary_distinct_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT DISTINCT customer_id FROM customers;")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("DISTINCT" in name for name in names))

    def test_order_by_without_limit_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT customer_id FROM orders ORDER BY total_amount DESC;")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("ORDER BY Without LIMIT" in name for name in names))

    def test_cartesian_product_detection(self):
        findings = self.linter.scan_anti_patterns("SELECT * FROM customers CROSS JOIN orders;")
        names = [f.pattern_name for f in findings]
        self.assertTrue(any("Cartesian" in name for name in names))

    def test_complexity_analysis(self):
        query = """
        SELECT c.name, COUNT(o.order_id)
        FROM customers c
        LEFT JOIN orders o ON c.customer_id = o.customer_id
        WHERE o.total_amount > 50 AND o.status = 'DELIVERED'
        GROUP BY c.name
        ORDER BY COUNT(o.order_id) DESC;
        """
        complexity = self.linter.analyze_complexity(query)
        self.assertGreaterEqual(complexity.join_count, 1)
        self.assertGreaterEqual(complexity.aggregation_count, 1)
        self.assertGreaterEqual(complexity.sort_count, 1)
        self.assertIn(complexity.risk_level, ["LOW", "MEDIUM", "HIGH"])


if __name__ == "__main__":
    unittest.main()
