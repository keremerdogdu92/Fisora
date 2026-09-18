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
