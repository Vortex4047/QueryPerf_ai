import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from schemas import (BenchmarkDistributionRequest, BenchmarkDistributionResponse,
                     BenchmarkMetrics, CompletionResponse, DashboardStats, EngineType,
                     HistoryEntry, MigrationArtifact, NaturalLanguageRequest,
                     NaturalLanguageResponse, OptimizationRequest, OptimizationResponse,
                     QueryPreview, WhatIfIndexResult, WhatIfSimRequest, WhatIfSimResponse,
                     BattleRequest, BattleResponse, CliffDetectorRequest, PerformanceCliff,
                     PlanHeatmapItem, VisualPlanNode)
from services.ai_service import QueryOptimizerAIService
from services.confidence_service import ConfidenceScoreService
from services.db_service import DatabaseSandboxService
from services.history_service import QueryHistoryService
from services.index_advisor import AdvancedIndexAdvisor
from services.linter_service import SQLLinterService
from services.multi_db_service import MultiDatabaseService
from services.nlp_service import NaturalLanguageSQLService
from services.plan_visualizer import PlanVisualizerService
from services.rewrite_engine import QueryRewriteEngine
from services.learned_optimizer import LearnedOptimizerService
from services.performance_predictor import PerformancePredictorService
from services.root_cause_service import RootCauseService
from services.battle_service import BattleArenaService
from services.experiment_service import ScientificExperimentService
from services.cliff_detector import PerformanceCliffService
from services.explainer_service import ExplainerService
from services.decision_tree_service import DecisionTreeService

BASE_DIR = Path(__file__).parent
app = FastAPI(title="QueryPerf AI", version="2.0.0")

allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"], max_age=600)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

_requests: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def security_controls(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.method not in {"GET", "POST"}:
        return JSONResponse({"detail": "Method not allowed."}, status_code=405)
    if request.method == "POST" and int(request.headers.get("content-length", "0") or 0) > 150_000:
        return JSONResponse({"detail": "Request body is too large."}, status_code=413)

    now, client = time.monotonic(), (request.client.host if request.client else "unknown")
    window = _requests[client]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= 60:
        return JSONResponse({"detail": "Too many requests. Please retry shortly."}, status_code=429)
    window.append(now)

    response = await call_next(request)
    response.headers.update({
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store",
    })
    return response


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "QueryPerf AI", "version": "2.0.0"}


@app.get("/api/history", response_model=list[HistoryEntry])
def history():
    return QueryHistoryService().list()


@app.get("/api/dashboard", response_model=DashboardStats)
def dashboard():
    return QueryHistoryService().get_dashboard_stats()


@app.post("/api/schema-completions", response_model=CompletionResponse)
def schema_completions(request: OptimizationRequest):
    sandbox = DatabaseSandboxService()
    try:
        conn, cursor = sandbox._initialize(request.ddl_schema)
        conn.set_authorizer(None)
        tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return CompletionResponse(
            tables={table: [col[1] for col in cursor.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")')] for table in tables},
            keywords=["SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "GROUP BY", "ORDER BY", "LIMIT", "EXPLAIN QUERY PLAN", "WITH", "EXISTS"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if "conn" in locals():
            conn.set_authorizer(sandbox._authorizer)
            conn.close()


def generate_plan_heatmap(visual_node: VisualPlanNode) -> list[PlanHeatmapItem]:
    items = []
    nodes = [visual_node]
    to_visit = [visual_node]
    while to_visit:
        curr = to_visit.pop(0)
        for ch in curr.children:
            nodes.append(ch)
            to_visit.append(ch)

    weights = []
    for n in nodes:
        w = 10
        if n.cost_level == "critical":
            w = 70
        elif n.cost_level == "warning":
            w = 35
        elif n.cost_level == "optimal":
            w = 15
        if "SCAN" in n.name.upper():
            w += 40
        weights.append(w)

    total_w = sum(weights) or 1
    for n, w in zip(nodes, weights):
        pct = round((w / total_w) * 100, 1)
        color = "bg-rose-500" if pct >= 40 else ("bg-amber-500" if pct >= 20 else "bg-emerald-500")
        tbl = n.table if n.table else "Relation Scan"
        items.append(PlanHeatmapItem(
            operator=n.name,
            table=tbl,
            percentage=pct,
            estimated_work=f"{pct}% execution time",
            color_class=color
        ))
    return sorted(items, key=lambda x: x.percentage, reverse=True)


@app.post("/api/optimize", response_model=OptimizationResponse)
def optimize(request: OptimizationRequest):
    sandbox = DatabaseSandboxService()
    visualizer = PlanVisualizerService()
    linter = SQLLinterService()
    rewrite_engine = QueryRewriteEngine()
    advisor = AdvancedIndexAdvisor()
    confidence_svc = ConfidenceScoreService()
    multi_db = MultiDatabaseService()

    try:
        sandbox.validate_read_only_query(request.slow_query)

        # 1. Capture Original Plan
        original_plan = sandbox.preview_execution_plan(request.ddl_schema, request.slow_query)

        # 2. AI / Deterministic Analysis
        analysis, analysis_engine = QueryOptimizerAIService().analyze(request.ddl_schema, request.slow_query, original_plan)

        # 3. Sandbox Execution & Benchmarking across all candidates & index options
        index_cmds = [item.index_command for item in analysis.index_recommendations]
        raw_candidates = rewrite_engine.generate_candidates(request.slow_query)
        result, rewrite_candidates, index_adv = sandbox.execute_full_suite(
            request.ddl_schema,
            request.slow_query,
            analysis.optimized_query,
            index_cmds,
            raw_candidates,
        )

        speedup_factor_num = round(result.original_ms / max(result.optimized_ms, 0.01), 1)
        speedup_pct = round(max(0.0, (result.original_ms - result.optimized_ms) / max(result.original_ms, 0.001) * 100), 1)

        # 4. History and Regression Detection with actual measured speedup and anti-patterns
        ap_names = [ap.pattern_name for ap in analysis.detected_anti_patterns]
        fingerprint, regression_alert = QueryHistoryService().record(
            request.slow_query,
            100 - analysis.health_score_original,
            f"{speedup_factor_num}x Faster",
            speedup_pct,
            result.original_ms,
            ap_names,
        )

        # 5. Visual Execution Plan Trees
        if request.engine == EngineType.SQLITE:
            visual_orig = visualizer.parse_sqlite_plan(result.execution_plan)
            visual_opt = visualizer.parse_sqlite_plan(result.optimized_execution_plan)
        else:
            _, visual_orig = multi_db.generate_dialect_plan(request.engine, request.slow_query, has_index=False)
            _, visual_opt = multi_db.generate_dialect_plan(request.engine, analysis.optimized_query, has_index=True)

        # 6. Query Complexity Analysis
        complexity = linter.analyze_complexity(request.slow_query)

        # 7. Confidence Score Breakdown
        confidence = confidence_svc.compute(
            result.original_ms,
            result.optimized_ms,
            result.execution_plan,
            result.optimized_execution_plan,
            result.optimized_preview_rows,
            analysis_engine,
            index_applied=len(index_cmds) > 0,
        )

        # 8. Raw SQL Migrations
        migrations = [
            MigrationArtifact(
                name=f"{item.index_command.split(' ON ')[0].replace('CREATE INDEX IF NOT EXISTS ', '')}.sql",
                up_sql=item.index_command,
                down_sql=f"DROP INDEX IF EXISTS {item.index_command.split(' ON ')[0].split()[-1]};"
            )
            for item in analysis.index_recommendations
        ]

        # 9. Advanced Viva & Intelligence Features
        performance_pred = PerformancePredictorService.predict(request.slow_query, request.ddl_schema, actual_ms=result.original_ms)
        learned_opt = LearnedOptimizerService.analyze_and_learn(request.slow_query, result.execution_plan, measured_speedup=speedup_pct)
        root_cause = RootCauseService.diagnose(request.slow_query, result.execution_plan, analysis.detected_anti_patterns, index_adv)
        scientific_exp = ScientificExperimentService.run_experiment(request.slow_query, request.ddl_schema, iterations=25)
        perf_cliff = PerformanceCliffService.detect_cliff(request.slow_query, request.ddl_schema)
        plan_heatmap = generate_plan_heatmap(visual_orig)
        dual_explainer = ExplainerService.generate_dual_explanation(request.slow_query, result.execution_plan)
        decision_tree = DecisionTreeService.build_tree(request.slow_query, result.execution_plan, len(analysis.detected_anti_patterns) > 0)

        return OptimizationResponse(
            **analysis.model_dump(),
            engine=request.engine,
            original_ms=result.original_ms,
            optimized_ms=result.optimized_ms,
            speedup_factor=f"{speedup_factor_num}x Faster",
            original_execution_plan=result.execution_plan,
            optimized_execution_plan=result.optimized_execution_plan,
            analysis_engine=analysis_engine,
            optimized_preview=QueryPreview(columns=result.optimized_preview_columns, rows=result.optimized_preview_rows),
            original_metrics=BenchmarkMetrics(
                execution_ms=result.original_ms,
                cpu_ms=result.original_cpu_ms,
                estimated_io_reads=result.original_io_reads,
                rows_returned=result.original_rows
            ),
            optimized_metrics=BenchmarkMetrics(
                execution_ms=result.optimized_ms,
                cpu_ms=result.optimized_cpu_ms,
                estimated_io_reads=result.optimized_io_reads,
                rows_returned=result.optimized_rows
            ),
            what_if_indexes=[WhatIfIndexResult(**item) for item in result.what_if_indexes],
            index_advisor=index_adv,
            rewrite_candidates=rewrite_candidates,
            visual_plan_original=visual_orig,
            visual_plan_optimized=visual_opt,
            complexity_analysis=complexity,
            confidence_breakdown=confidence,
            regression_alert=regression_alert,
            migrations=migrations,
            query_fingerprint=fingerprint,
            strict_linter_enabled=True,
            performance_prediction=performance_pred,
            learned_optimization=learned_opt,
            root_cause_tree=root_cause,
            scientific_experiment=scientific_exp,
            performance_cliff=perf_cliff,
            plan_heatmap=plan_heatmap,
            dual_persona_explainer=dual_explainer,
            decision_tree=decision_tree,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis could not be completed safely: {exc}") from exc


@app.post("/api/battle", response_model=BattleResponse)
def battle_arena(request: BattleRequest):
    """SQL Optimization Battle Arena Tournament."""
    try:
        return BattleArenaService.execute_tournament(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Battle tournament failed: {exc}") from exc


@app.post("/api/cliff-detector", response_model=PerformanceCliff)
def cliff_detector_endpoint(request: CliffDetectorRequest):
    """Performance Cliff & Cardinality Scaling Detector."""
    try:
        return PerformanceCliffService.detect_cliff(request.query, request.ddl_schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cliff detection failed: {exc}") from exc


@app.post("/api/what-if", response_model=WhatIfSimResponse)
def what_if_simulator(request: WhatIfSimRequest):
    """Interactive What-If Index Simulator ("Index Lab")."""
    sandbox = DatabaseSandboxService()
    try:
        return sandbox.simulate_custom_index(request.ddl_schema, request.query, request.index_command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Index simulation failed: {exc}") from exc


@app.post("/api/nl-to-sql", response_model=NaturalLanguageResponse)
def natural_language_copilot(request: NaturalLanguageRequest):
    """Translates natural language to schema-aware SQL."""
    nlp = NaturalLanguageSQLService()
    try:
        return nlp.translate_to_sql(request.prompt, request.ddl_schema, request.engine)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Copilot translation failed: {exc}") from exc


@app.post("/api/benchmark-distribution", response_model=BenchmarkDistributionResponse)
def benchmark_distribution(request: BenchmarkDistributionRequest):
    """Executes multi-run distribution benchmarks."""
    sandbox = DatabaseSandboxService()
    try:
        return sandbox.benchmark_distribution(request.ddl_schema, request.query, request.iterations)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Distribution benchmark failed: {exc}") from exc
