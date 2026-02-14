from libs.neural_flow.observability import bind_log_context, configure_logging, get_logger, query_logs


def test_logs_can_be_collected_and_queried_by_trace(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "system_logs.db"
    monkeypatch.setenv("LOG_DB_PATH", str(db_path))
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    configure_logging("unit_test_service")
    logger = get_logger("unit_test_logger")

    with bind_log_context(trace_id="trace-unit-001", request_id="req-001"):
        logger.info("log_for_trace", extra={"stage": "collect"})

    items = query_logs(trace_id="trace-unit-001", limit=20)
    assert items
    assert items[0]["trace_id"] == "trace-unit-001"
    assert items[0]["service"] == "unit_test_service"
    assert items[0]["message"] == "log_for_trace"
