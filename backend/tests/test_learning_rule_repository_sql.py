from app.persistence.learning_rule_repository import LearningRuleRepository

class RecordingCursor:
    def __init__(self):
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), tuple(params)))
    def fetchall(self):
        return []

class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def cursor(self):
        return self._cursor

def test_list_active_without_rule_key_uses_no_untyped_null_placeholder():
    cursor = RecordingCursor()
    repo = LearningRuleRepository(
        connect=lambda: RecordingConnection(cursor),
        tenant_id="00000000-0000-0000-0000-000000000001",
    )
    assert repo.list_active() == []
    sql, params = cursor.calls[-1]
    assert " is null " not in sql.lower()
    assert "rule_key = %s" not in sql
    assert params == ("00000000-0000-0000-0000-000000000001",)

def test_list_active_with_rule_key_adds_typed_equality_filter():
    cursor = RecordingCursor()
    repo = LearningRuleRepository(
        connect=lambda: RecordingConnection(cursor),
        tenant_id="00000000-0000-0000-0000-000000000001",
    )
    assert repo.list_active(rule_key="rule-a") == []
    sql, params = cursor.calls[-1]
    assert "rule_key = %s" in sql
    assert params == ("00000000-0000-0000-0000-000000000001", "rule-a")

def test_workflow_review_provenance_does_not_fill_normalized_review_fk():
    repo = LearningRuleRepository(tenant_id="00000000-0000-0000-0000-000000000001")
    workflow_review_id = "11111111-1111-1111-1111-111111111111"
    row = repo._new_row(
        "client:test:purchase:client_phrase:fisora-pilot",
        None,
        {
            "scope": "client_phrase",
            "source_review_decision_id": workflow_review_id,
            "source_review_reference_kind": "workflow",
        },
        "accountant",
    )

    values = repo._insert_values(row)

    assert values[3] is None
    assert row["source_review_decision_id"] == workflow_review_id


def test_normalized_review_provenance_fills_normalized_review_fk():
    repo = LearningRuleRepository(tenant_id="00000000-0000-0000-0000-000000000001")
    normalized_review_id = "22222222-2222-2222-2222-222222222222"
    row = repo._new_row(
        "client:test:purchase:client_phrase:fisora-pilot",
        None,
        {
            "scope": "client_phrase",
            "source_review_decision_id": normalized_review_id,
            "source_review_reference_kind": "normalized",
        },
        "accountant",
    )

    values = repo._insert_values(row)

    assert values[3] == normalized_review_id
