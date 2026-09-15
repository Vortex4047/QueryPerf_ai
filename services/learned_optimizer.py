import datetime
import logging
import re
import sqlite3
from schemas import LearnedOptimization
from services.db_storage import get_storage_db_path

logger = logging.getLogger(__name__)


class LearnedOptimizerService:
    @classmethod
    def get_db_path(cls) -> str:
        return get_storage_db_path(".queryperf_history.sqlite")

    @classmethod
    def _init_db(cls):
        db_path = cls.get_db_path()
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA temp_store = 2")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS learned_optimizer_patterns (
                        pattern_id TEXT PRIMARY KEY,
                        query_type TEXT,
                        signature TEXT,
                        recommended_strategy TEXT,
                        avg_speedup REAL,
                        precedent_count INTEGER,
                        last_updated TEXT
                    );
                    """
                )
                # Check if seeded
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM learned_optimizer_patterns")
                if cur.fetchone()[0] == 0:
                    seed_patterns = [
                        (
                            "scan_filter_customer",
                            "Filter on unindexed Foreign Key",
                            "SCAN:orders|FILTER:customer_id",
                            "Add composite covering index orders(customer_id, status)",
                            84.5,
                            18,
                        ),
                        (
                            "anti_pattern_not_in",
                            "Subquery Anti-Join with NOT IN",
                            "SUBQUERY:NOT_IN|TABLE:orders",
                            "Refactor NOT IN to NOT EXISTS or LEFT JOIN ... IS NULL",
                            64.2,
                            12,
                        ),
                        (
                            "wildcard_prefix_search",
                            "Leading Wildcard LIKE filter",
                            "FILTER:LIKE_WILDCARD",
                            "Convert to SARGable prefix search or Full-Text search index",
                            78.0,
                            9,
                        ),
                        (
                            "cartesian_join_implicit",
                            "Cartesian Join / Comma syntax",
                            "JOIN:IMPLICIT_COMMA",
                            "Refactor to explicit INNER JOIN with selective ON conditions",
                            92.4,
                            15,
                        ),
                        (
                            "order_by_unindexed_sort",
                            "External Temp B-Tree / Filesort",
                            "PLAN:USE_TEMP_BTREE_FOR_ORDER_BY",
                            "Create composite index matching (filter_col, sort_col)",
                            71.5,
                            14,
                        ),
                    ]
                    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    for pid, qtype, sig, strat, sp, cnt in seed_patterns:
                        cur.execute(
                            """
                            INSERT INTO learned_optimizer_patterns 
                            (pattern_id, query_type, signature, recommended_strategy, avg_speedup, precedent_count, last_updated)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (pid, qtype, sig, strat, sp, cnt, now),
                        )
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize learned optimizer database at {db_path}: {exc}")

    @classmethod
    def extract_signature(cls, query: str, plan_text: str) -> tuple[str, str]:
        q_upper = query.upper()
        plan_upper = plan_text.upper()

        if "NOT IN" in q_upper and "SELECT" in q_upper:
            return "anti_pattern_not_in", "SUBQUERY:NOT_IN|TABLE:orders"
        if "LIKE '%" in q_upper or 'LIKE "%' in q_upper:
            return "wildcard_prefix_search", "FILTER:LIKE_WILDCARD"
        if "USE TEMP B-TREE FOR ORDER BY" in plan_upper:
            return "order_by_unindexed_sort", "PLAN:USE_TEMP_BTREE_FOR_ORDER_BY"
        if re.search(r"FROM\s+[a-zA-Z0-9_]+\s*,\s*[a-zA-Z0-9_]+", q_upper):
            return "cartesian_join_implicit", "JOIN:IMPLICIT_COMMA"
        if "SCAN" in plan_upper and "CUSTOMER" in q_upper:
            return "scan_filter_customer", "SCAN:orders|FILTER:customer_id"

        return (
            "generic_table_scan",
            f"SCAN:GENERIC|JOIN_COUNT:{q_upper.count('JOIN')}",
        )

    @classmethod
    def analyze_and_learn(
        cls,
        query: str,
        plan_text: str,
        measured_speedup: float | None = None,
        applied_optimization: str | None = None,
    ) -> LearnedOptimization:
        cls._init_db()
        pattern_id, signature = cls.extract_signature(query, plan_text)

        # Baseline defaults
        defaults_by_pattern = {
            "scan_filter_customer": ("Filter on unindexed Foreign Key", "Add composite covering index orders(customer_id, status)", 84.5, 18),
            "anti_pattern_not_in": ("Subquery Anti-Join with NOT IN", "Refactor NOT IN to NOT EXISTS or LEFT JOIN ... IS NULL", 64.2, 12),
            "wildcard_prefix_search": ("Leading Wildcard LIKE filter", "Convert to SARGable prefix search or Full-Text search index", 78.0, 9),
            "cartesian_join_implicit": ("Cartesian Join / Comma syntax", "Refactor to explicit INNER JOIN with selective ON conditions", 92.4, 15),
            "order_by_unindexed_sort": ("External Temp B-Tree / Filesort", "Create composite index matching (filter_col, sort_col)", 71.5, 14),
            "generic_table_scan": ("Unindexed Sequential Scan", "Apply composite index matching dominant WHERE filter predicates", 65.0, 5),
        }
        qtype, rec_strat, avg_sp, prec_cnt = defaults_by_pattern.get(
            pattern_id, ("Unindexed Sequential Scan", "Apply composite index matching dominant WHERE filter predicates", 65.0, 5)
        )

        db_path = cls.get_db_path()
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT pattern_id, query_type, signature, recommended_strategy, avg_speedup, precedent_count FROM learned_optimizer_patterns WHERE pattern_id = ?",
                    (pattern_id,),
                )
                row = cur.fetchone()

                if not row:
                    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    cur.execute(
                        """
                        INSERT INTO learned_optimizer_patterns 
                        (pattern_id, query_type, signature, recommended_strategy, avg_speedup, precedent_count, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (pattern_id, qtype, signature, rec_strat, avg_sp, prec_cnt, now),
                    )
                    conn.commit()
                else:
                    _, qtype, _, rec_strat, avg_sp, prec_cnt = row

                # Feedback loop: Update learning database with actual benchmark
                if (
                    measured_speedup is not None
                    and measured_speedup > 0
                    and measured_speedup < 1000
                ):
                    new_cnt = prec_cnt + 1
                    new_avg = round(
                        ((avg_sp * prec_cnt) + measured_speedup) / new_cnt, 1
                    )
                    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    cur.execute(
                        """
                        UPDATE learned_optimizer_patterns 
                        SET avg_speedup = ?, precedent_count = ?, last_updated = ?
                        WHERE pattern_id = ?
                        """,
                        (new_avg, new_cnt, now, pattern_id),
                    )
                    conn.commit()
                    avg_sp = new_avg
                    prec_cnt = new_cnt
        except Exception as exc:
            logger.warning(f"Learned optimizer could not query SQLite at {db_path}: {exc}")

        confidence = min(98, 60 + (prec_cnt * 2))

        return LearnedOptimization(
            query_signature=signature,
            matched_historical_pattern=qtype,
            recommended_strategy=rec_strat,
            historical_speedup_avg=avg_sp,
            precedent_count=prec_cnt,
            confidence_score=confidence,
        )

