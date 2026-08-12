-- Canonical reconstruction query for the bounded report snapshot.
-- The evidence and commands behind these reviewed rows are in
-- docs/report/verification-summary.md.
WITH reviewed_rows(dataset, row_json) AS (
    VALUES
        ('stage_metric', '{"value":7}'),
        ('backend_test_metric', '{"passed":438,"skipped":1}'),
        ('frontend_test_metric', '{"unit_passed":79,"e2e_passed":8}'),
        ('stage_completion', '{"stage_label":"1. Storage","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_completion', '{"stage_label":"2. Anomaly","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_completion', '{"stage_label":"3. Auth","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_completion', '{"stage_label":"4. Backend","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_completion', '{"stage_label":"5. Frontend","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_completion', '{"stage_label":"6. Integration","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_completion', '{"stage_label":"7. Operations","completion_rate":1,"p0_p1_remaining":0}'),
        ('stage_results', '{"stage":1,"area":"JSON storage foundation","review":"P0/P1 없음"}'),
        ('stage_results', '{"stage":2,"area":"Anomaly v1.4","review":"P0/P1 없음"}'),
        ('stage_results', '{"stage":3,"area":"Auth and authorization","review":"P0/P1 없음"}'),
        ('stage_results', '{"stage":4,"area":"Backend product APIs","review":"P0/P1 없음"}'),
        ('stage_results', '{"stage":5,"area":"Frontend product flow","review":"P0/P1 없음"}'),
        ('stage_results', '{"stage":6,"area":"Integration acceptance","review":"P0/P1 없음"}'),
        ('stage_results', '{"stage":7,"area":"Operations and release","review":"P0/P1 없음"}'),
        ('before_after', '{"priority":1,"area":"Anomaly"}'),
        ('before_after', '{"priority":2,"area":"Tablet journey"}'),
        ('before_after', '{"priority":3,"area":"Conversation"}'),
        ('before_after', '{"priority":4,"area":"Security"}'),
        ('before_after', '{"priority":5,"area":"Persistence"}'),
        ('before_after', '{"priority":6,"area":"Release"}'),
        ('quality_gates', '{"order":1,"scope":"Backend","gate":"pytest","result":"438 passed, 1 skipped"}'),
        ('quality_gates', '{"order":2,"scope":"Backend","gate":"Ruff · mypy · OpenAPI","result":"통과"}'),
        ('quality_gates', '{"order":3,"scope":"Frontend","gate":"Vitest · ESLint · TypeScript","result":"79 passed · clean"}'),
        ('quality_gates', '{"order":4,"scope":"Frontend","gate":"production · demo build","result":"통과"}'),
        ('quality_gates', '{"order":5,"scope":"Browser","gate":"Playwright Tablet E2E","result":"8 passed"}'),
        ('quality_gates', '{"order":6,"scope":"Container · Ops","gate":"image build · deploy review","result":"통과"}'),
        ('history_periods', '{"order":1,"period":"프로젝트 수행 기간","be_commits":102,"fe_commits":9}'),
        ('history_periods', '{"order":2,"period":"후속 완성 작업","author_date":"2026-08-13"}')
)
SELECT dataset, row_json
FROM reviewed_rows
ORDER BY dataset, row_json;
