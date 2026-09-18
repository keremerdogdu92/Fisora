from app.api.phase0_routes_learning_rules import _learning_rule_backend_reason

class MissingTable(Exception):
    sqlstate = "42P01"

class MissingColumn(Exception):
    sqlstate = "42703"

class DataProblem(Exception):
    sqlstate = "22023"

class ConnectionProblem(Exception):
    sqlstate = "08006"

def test_learning_rule_backend_reason_classifies_safe_categories() -> None:
    assert _learning_rule_backend_reason(MissingTable()) == "learning_rules_table_missing"
    assert _learning_rule_backend_reason(MissingColumn()) == "learning_rules_schema_outdated"
    assert _learning_rule_backend_reason(DataProblem()) == "learning_rules_data_invalid"
    assert _learning_rule_backend_reason(ConnectionProblem()) == "learning_rules_database_unavailable"
    assert _learning_rule_backend_reason(RuntimeError()) == "learning_rules_backend_error"
