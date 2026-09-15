from enum import Enum
from pydantic import BaseModel, Field, field_validator


class EngineType(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MYSQL = "mysql"


class OptimizationRequest(BaseModel):
    ddl_schema: str = Field(min_length=10, max_length=50_000)
    slow_query: str = Field(min_length=6, max_length=50_000)
    engine: EngineType = Field(default=EngineType.SQLITE)

    @field_validator("ddl_schema", "slow_query")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field cannot be blank.")
        return value.strip()


class AntiPattern(BaseModel):
    pattern_name: str
    severity: str = "HIGH"  # CRITICAL, HIGH, MEDIUM, LOW
    estimated_impact: str = "High"  # High, Medium, Low
    why: str
    suggested_rewrite: str
    category: str = "Performance"


class IndexRecommendation(BaseModel):
    index_command: str
    reason: str


class IndexCostBenefit(BaseModel):
    index_name: str
    table: str
    columns: list[str]
    command: str
    estimated_benefit_percent: float
    query_improvement_ms: float
    before_ms: float
    after_ms: float
    star_rating: int = Field(ge=1, le=100)
    tradeoffs_pros: list[str]
    tradeoffs_cons: list[str]


class WhatIfIndexResult(BaseModel):
    index_command: str
    before_ms: float
    after_ms: float
    estimated_gain_percent: float
    plan_changed: bool


class WhatIfSimRequest(BaseModel):
    ddl_schema: str = Field(min_length=10, max_length=50_000)
    query: str = Field(min_length=6, max_length=50_000)
    index_command: str = Field(min_length=10, max_length=2_000)
    engine: EngineType = Field(default=EngineType.SQLITE)


class VisualPlanNode(BaseModel):
    id: str
    name: str
    operation_type: str  # scan, search, temp_btree, sort, join, filter, aggregate, result
    cost_level: str  # critical, warning, optimal, neutral
    detail: str
    table: str = ""
    index_name: str = ""
    rows_est: int = 0
    explanation: str = ""
    children: list["VisualPlanNode"] = []


class WhatIfSimResponse(BaseModel):
    index_command: str
    valid: bool
    verdict: str  # Useful, Redundant, Detrimental
    before_ms: float
    after_ms: float
    speedup_percent: float
    explanation: str
    plan_before: str
    plan_after: str
    visual_plan_before: VisualPlanNode
    visual_plan_after: VisualPlanNode


class BenchmarkMetrics(BaseModel):
    execution_ms: float
    cpu_ms: float
    estimated_io_reads: int
    rows_returned: int


class MigrationArtifact(BaseModel):
    name: str
    up_sql: str
    down_sql: str


class QueryPreview(BaseModel):
    columns: list[str]
    rows: list[list[str]]


class RewriteCandidate(BaseModel):
    id: str
    title: str
    strategy: str  # JOIN Refactor, EXISTS Semi-join, CTE Window
    query: str
    execution_ms: float
    cpu_ms: float
    plan_summary: str
    is_best: bool = False
    speedup_percent: float = 0.0


class QueryComplexity(BaseModel):
    join_count: int
    subquery_count: int
    aggregation_count: int
    sort_count: int
    filter_count: int
    risk_level: str  # LOW, MEDIUM, HIGH
    dominant_cost_factor: str
    explanation: str


class ConfidenceCheckItem(BaseModel):
    label: str
    passed: bool
    impact: str


class ConfidenceBreakdown(BaseModel):
    score: int = Field(ge=0, le=100)
    level: str  # HIGH, MEDIUM, LOW
    checklist: list[ConfidenceCheckItem]
    penalties: list[str] = []


class RegressionAlert(BaseModel):
    is_regression: bool = False
    fingerprint: str = ""
    previous_ms: float = 0.0
    current_ms: float = 0.0
    regression_percent: float = 0.0
    likely_cause: str = ""
    recommendation: str = ""


class AIAnalysis(BaseModel):
    health_score_original: int = Field(ge=0, le=100)
    health_score_optimized: int = Field(ge=0, le=100)
    detected_anti_patterns: list[AntiPattern]
    bottleneck_analysis: str
    original_plan_summary: str
    optimized_query: str
    index_recommendations: list[IndexRecommendation]
    time_complexity_improvement: str
    key_takeaway: str


class PerformancePrediction(BaseModel):
    predicted_min_ms: float
    predicted_max_ms: float
    predicted_rows: int
    predicted_bottleneck: str
    risk_level: str  # LOW, MEDIUM, HIGH
    actual_ms: float = 0.0
    accuracy_percent: float = 0.0


class LearnedOptimization(BaseModel):
    query_signature: str
    matched_historical_pattern: str
    recommended_strategy: str
    historical_speedup_avg: float
    precedent_count: int
    confidence_score: int


class RootCauseNode(BaseModel):
    id: str
    level: int
    title: str
    description: str
    category: str  # symptom, operator, planner, smell, remediation
    code_snippet: str = ""
    metric_impact: str = ""
    children: list["RootCauseNode"] = []


class BattleParticipant(BaseModel):
    name: str
    type: str  # original, ai_rewrite, index_advisor, human
    query: str
    execution_ms: float
    speedup_percent: float
    is_winner: bool = False
    rank: int = 1
    summary: str = ""


class BattleRequest(BaseModel):
    ddl_schema: str = Field(min_length=10, max_length=50_000)
    original_query: str = Field(min_length=6, max_length=50_000)
    human_query: str = ""


class BattleResponse(BaseModel):
    participants: list[BattleParticipant]
    winner_name: str
    tournament_summary: str


class ScientificExperiment(BaseModel):
    hypothesis: str
    control_label: str
    control_mean_ms: float
    control_std_dev: float
    treatment_label: str
    treatment_mean_ms: float
    treatment_std_dev: float
    iterations: int
    speedup_percent: float
    statistically_significant: bool
    p_value_text: str
    conclusion: str


class PerformanceCliff(BaseModel):
    curve_type: str  # logarithmic, linear, quadratic, exponential
    cliff_detected: bool
    cliff_threshold_rows: int
    data_points: list[dict]
    explanation: str


class CliffDetectorRequest(BaseModel):
    ddl_schema: str = Field(min_length=10, max_length=50_000)
    query: str = Field(min_length=6, max_length=50_000)


class PlanHeatmapItem(BaseModel):
    operator: str
    table: str
    percentage: float
    estimated_work: str
    color_class: str


class ExplainableStep(BaseModel):
    step_number: int
    phase: str
    headline: str
    beginner_analogy: str
    dba_technical_insight: str


class DecisionTreeNode(BaseModel):
    id: str
    question: str
    answer: str
    condition_met: bool
    action_taken: str
    next_node_id: str = ""


class OptimizationResponse(AIAnalysis):
    engine: EngineType = EngineType.SQLITE
    original_ms: float = Field(ge=0)
    optimized_ms: float = Field(ge=0)
    speedup_factor: str
    original_execution_plan: str
    optimized_execution_plan: str
    analysis_engine: str
    optimized_preview: QueryPreview
    original_metrics: BenchmarkMetrics
    optimized_metrics: BenchmarkMetrics
    what_if_indexes: list[WhatIfIndexResult]
    index_advisor: list[IndexCostBenefit] = []
    rewrite_candidates: list[RewriteCandidate] = []
    visual_plan_original: VisualPlanNode
    visual_plan_optimized: VisualPlanNode
    complexity_analysis: QueryComplexity
    confidence_breakdown: ConfidenceBreakdown
    regression_alert: RegressionAlert
    migrations: list[MigrationArtifact]
    query_fingerprint: str
    strict_linter_enabled: bool = True
    performance_prediction: PerformancePrediction | None = None
    learned_optimization: LearnedOptimization | None = None
    root_cause_tree: RootCauseNode | None = None
    scientific_experiment: ScientificExperiment | None = None
    performance_cliff: PerformanceCliff | None = None
    plan_heatmap: list[PlanHeatmapItem] = []
    dual_persona_explainer: list[ExplainableStep] = []
    decision_tree: list[DecisionTreeNode] = []


class CompletionResponse(BaseModel):
    tables: dict[str, list[str]]
    keywords: list[str]


class HistoryEntry(BaseModel):
    fingerprint: str
    query_preview: str
    inefficiency_score: int
    runs: int
    latest_speedup: str
    last_seen: str
    execution_ms: float = 0.0


class DashboardStats(BaseModel):
    total_queries_analyzed: int
    average_speedup_percent: float
    total_regressions_detected: int
    total_indexes_recommended: int
    top_slow_queries: list[dict]
    antipattern_distribution: dict[str, int]
    recent_history: list[HistoryEntry]


class NaturalLanguageRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1_000)
    ddl_schema: str = Field(min_length=10, max_length=50_000)
    engine: EngineType = Field(default=EngineType.SQLITE)


class NaturalLanguageResponse(BaseModel):
    generated_sql: str
    explanation: str
    identified_entities: list[str]
    confidence_score: int


class BenchmarkDistributionRequest(BaseModel):
    ddl_schema: str
    query: str
    iterations: int = Field(default=25, ge=5, le=100)


class BenchmarkDistributionResponse(BaseModel):
    iterations: int
    min_ms: float
    max_ms: float
    median_ms: float
    avg_ms: float
    p95_ms: float
    samples: list[float]
    distribution_buckets: list[dict]
