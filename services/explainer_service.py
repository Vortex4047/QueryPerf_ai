from schemas import ExplainableStep


class ExplainerService:
    @classmethod
    def generate_dual_explanation(
        cls, query: str, plan_text: str, index_rec_name: str = ""
    ) -> list[ExplainableStep]:
        steps = []

        # Step 1: Ingestion & Filter Parse
        steps.append(
            ExplainableStep(
                step_number=1,
                phase="Query Parsing & Predicate Evaluation",
                headline="The database identifies what records you asked for",
                beginner_analogy="Think of this like walking into a grocery store with a shopping list. You need to locate specific items across multiple aisles.",
                dba_technical_insight="The SQL parser tokenizes the statement into an AST, extracts WHERE predicates, and checks column sargability against the schema catalog.",
            )
        )

        # Step 2: Data Retrieval / Scan Strategy
        if "SCAN" in plan_text.upper():
            steps.append(
                ExplainableStep(
                    step_number=2,
                    phase="Physical Relation Access (Table Scan)",
                    headline="The database reads every single row in the table",
                    beginner_analogy="Instead of using a book's index at the back, you are flipping through all 500 pages one by one to find every mention of a word.",
                    dba_technical_insight="Cost-based optimizer bypassed index seek and initiated a sequential scan (SCAN TABLE), loading full 4KB database pages into the buffer pool.",
                )
            )
        else:
            steps.append(
                ExplainableStep(
                    step_number=2,
                    phase="Indexed Range Seek",
                    headline="The database jumps directly to matching records",
                    beginner_analogy="Like using the alphabetical tabs on a phone directory to flip immediately to the 'Smith' section in 2 seconds.",
                    dba_technical_insight="Traversing B-Tree root -> branch -> leaf nodes in O(log N) page reads, achieving direct rowid pointer dereferencing.",
                )
            )

        # Step 3: Join / Correlation Operation
        if "JOIN" in query.upper() or "," in query:
            steps.append(
                ExplainableStep(
                    step_number=3,
                    phase="Relational Join Execution",
                    headline="Matching customer records with corresponding order records",
                    beginner_analogy="Cross-referencing two paper receipts to check if the receipt numbers and customer names match up.",
                    dba_technical_insight="Executing nested loop or hash join. For each outer row from customers, the inner relation is probed for matching foreign keys.",
                )
            )

        # Step 4: Sorting & Result Aggregation
        steps.append(
            ExplainableStep(
                step_number=4,
                phase="Projection & Result Buffering",
                headline="Assembling and returning the final result set",
                beginner_analogy="Putting the matched receipts in chronological order on your desk before handing them to the accountant.",
                dba_technical_insight="Materializing output columns into cursor memory, evaluating aggregate functions, and streaming records through the connection socket.",
            )
        )

        # Step 5: Optimization Impact
        steps.append(
            ExplainableStep(
                step_number=5,
                phase="The Optimization Difference",
                headline="Why the optimized version runs drastically faster",
                beginner_analogy="Adding a bookmark and labeled sticky note so the librarian can instantly grab the exact folder without searching the entire warehouse.",
                dba_technical_insight=f"The composite index allows index-only or selective index-seek access, eliminating disk page thrashing and reducing instruction cycles by up to 85%.",
            )
        )

        return steps
