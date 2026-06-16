"""Tests for error log system — V4.9"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestErrorLog:
    """Test AppState error log collection and API."""

    def test_add_error(self):
        """Adding an error increments count and adds entry."""
        from app.bridge.app_state import AppState
        state = AppState()
        initial_count = state.errorLogCount

        state._add_error_log("测试", "测试错误消息")
        assert state.errorLogCount == initial_count + 1

        logs = state.getErrorLog()
        assert len(logs) >= 1
        last = logs[-1]
        assert last["level"] == "测试"
        assert last["message"] == "测试错误消息"
        assert "time" in last

    def test_clear_error_log(self):
        """Clearing error log resets count to 0."""
        from app.bridge.app_state import AppState
        state = AppState()
        state._add_error_log("测试", "test")
        state.clearErrorLog()
        assert state.errorLogCount == 0
        assert len(state.getErrorLog()) == 0

    def test_max_entries(self):
        """Error log caps at 100 entries."""
        from app.bridge.app_state import AppState
        state = AppState()
        for i in range(150):
            state._add_error_log("测试", f"消息 {i}")
        assert len(state.getErrorLog()) <= 100
        logs = state.getErrorLog()
        assert "消息 149" == logs[-1]["message"]
