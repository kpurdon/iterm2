"""Retirement behavior against a simulated iTerm API; no live terminals are changed."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/tabs/scripts"))
import tabs
from terminal import close_tab, ungroup_tab


class FakeAPI:
    def __init__(self, *, missing=False, remains=False, close_error=None,
                 refresh_error_at=None, runner_error=None, skip_callback=False):
        self.target = SimpleNamespace(tab_id="target", window=SimpleNamespace(window_id="window"),
                                      async_close=self.close)
        self.other = SimpleNamespace(tab_id="other")
        self.tabs = {"other": self.other}
        if not missing:
            self.tabs["target"] = self.target
        self.remains = remains
        self.close_error = close_error
        self.refresh_error_at = refresh_error_at
        self.runner_error = runner_error
        self.skip_callback = skip_callback
        self.close_calls = []
        self.refreshes = 0

    async def async_get_app(self, connection):
        return self

    async def async_refresh(self):
        self.refreshes += 1
        if self.refreshes == self.refresh_error_at:
            raise RuntimeError("refresh failed")

    def get_tab_by_id(self, tab_id):
        return self.tabs.get(tab_id)

    async def close(self, *, force):
        self.close_calls.append(force)
        if self.close_error:
            raise self.close_error
        if not self.remains:
            del self.tabs["target"]

    def run_until_complete(self, callback):
        if not self.skip_callback:
            asyncio.run(callback(None))
        if self.runner_error:
            raise self.runner_error


class CloseTests(unittest.TestCase):
    def test_closes_only_exact_target_and_verifies_absence(self):
        for force in (False, True):
            with self.subTest(force=force):
                api = FakeAPI()
                result = close_tab("target", force=force, api=api)
                self.assertEqual(result, {"close": "confirmed", "tab_id": "target", "window_id": "window"})
                self.assertEqual(api.close_calls, [force])
                self.assertEqual(api.refreshes, 2)
                self.assertEqual(list(api.tabs), ["other"])

    def test_pre_request_failures_never_close(self):
        for options in ({"missing": True}, {"refresh_error_at": 1}, {"skip_callback": True},
                        {"skip_callback": True, "runner_error": RuntimeError("connection failed")}):
            with self.subTest(options=options):
                api = FakeAPI(**options)
                with self.assertRaises(RuntimeError):
                    close_tab("target", api=api)
                self.assertEqual(api.close_calls, [])

    def test_uncertainty_preserves_target_and_never_retries(self):
        for options in ({"remains": True}, {"refresh_error_at": 2},
                        {"close_error": RuntimeError("USER_DECLINED")},
                        {"close_error": ConnectionError("disconnected")},
                        {"close_error": asyncio.CancelledError()}):
            with self.subTest(options=options):
                api = FakeAPI(**options)
                result = close_tab("target", api=api)
                self.assertEqual(result["close"], "uncertain")
                self.assertEqual(result["tab_id"], "target")
                self.assertIn("reconcile before retrying", result["warning"])
                self.assertEqual(api.close_calls, [False])
                self.assertIn("other", api.tabs)

    def test_runner_error_after_verification_keeps_confirmed_result(self):
        result = close_tab("target", api=FakeAPI(runner_error=RuntimeError("disconnect")))
        self.assertEqual(result["close"], "confirmed")
        self.assertIn("closure was verified", result["warning"])


class GroupAPI(FakeAPI):
    def __init__(self, *, shared=False, disappears=False, group_remains=False, **options):
        super().__init__(**options)
        self.group = SimpleNamespace(group_id="group")
        self.target.tab_group = self.group
        self.other.tab_group = self.group if shared else None
        self.target.async_remove_from_tab_group = self.ungroup
        self.target.window.tabs = list(self.tabs.values())
        self.target.window.tab_groups = [self.group]
        self.terminal_windows = [self.target.window]
        self.disappears = disappears
        self.group_remains = group_remains
        self.ungroup_calls = 0

    async def ungroup(self):
        self.ungroup_calls += 1
        if not self.remains:
            self.target.tab_group = None
            if not self.group_remains:
                self.target.window.tab_groups = []
        if self.disappears:
            del self.tabs["target"]


class UngroupTests(unittest.TestCase):
    def ungroup(self, api, group_id="group"):
        with tempfile.TemporaryDirectory() as directory:
            return ungroup_tab("target", group_id, api=api, lock_path=Path(directory) / "launch.lock")

    def test_dissolves_group_without_closing_any_tabs(self):
        api = GroupAPI()
        result = self.ungroup(api)
        self.assertEqual(result["ungroup"], "confirmed")
        self.assertIs(api.tabs["target"], api.target)
        self.assertIsNone(api.target.tab_group)
        self.assertEqual(api.target.window.tab_groups, [])
        self.assertIn("other", api.tabs)
        self.assertEqual(api.close_calls, [])

    def test_refuses_other_members_missing_tab_and_wrong_group(self):
        for options, group_id in (({"shared": True}, "group"), ({"missing": True}, "group"),
                                  ({}, "wrong"), ({"refresh_error_at": 1}, "group")):
            with self.subTest(options=options, group_id=group_id):
                api = GroupAPI(**options)
                with self.assertRaises(RuntimeError):
                    self.ungroup(api, group_id)
                self.assertEqual(api.ungroup_calls, 0)
                self.assertEqual(api.close_calls, [])

    def test_unverified_dissolution_never_claims_success_or_retries(self):
        for options in ({"remains": True}, {"refresh_error_at": 2}, {"disappears": True},
                        {"group_remains": True}):
            with self.subTest(options=options):
                api = GroupAPI(**options)
                result = self.ungroup(api)
                self.assertEqual(result["ungroup"], "uncertain")
                self.assertIn("reconcile before retrying", result["warning"])
                self.assertEqual(api.ungroup_calls, 1)
                self.assertEqual(api.close_calls, [])


class CLITests(unittest.TestCase):
    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = tabs.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_requires_explicit_valid_id(self):
        for argv in (["close"], ["close", "--tab-id", ""], ["close", "--tab-id", "\n"],
                     ["close", "--tab-id", "target", "--desktop"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    tabs.parse_args(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_dry_run_does_not_connect_or_resolve_origin_on_any_platform(self):
        with patch.object(tabs.sys, "platform", "linux"), patch.object(tabs, "close_tab") as close, \
                patch.object(tabs, "resolve_origin") as origin:
            status, stdout, _ = self.invoke(["close", "--tab-id", "target", "--force", "--dry-run"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout), {"close": "dry-run", "tab_id": "target", "destination": "unverified"})
        close.assert_not_called()
        origin.assert_not_called()

    def test_live_close_requires_macos(self):
        with patch.object(tabs.sys, "platform", "linux"), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                tabs.parse_args(["close", "--tab-id", "target"])

    def test_routes_close_and_reports_status(self):
        for outcome, expected in (("confirmed", 0), ("uncertain", 3)):
            result = {"close": outcome, "tab_id": "target"}
            if outcome == "uncertain":
                result["warning"] = "reconcile before retrying"
            with self.subTest(outcome=outcome), patch.object(tabs.sys, "platform", "darwin"), \
                    patch.object(tabs, "close_tab", return_value=result) as close:
                status, stdout, stderr = self.invoke(["close", "--tab-id", "target", "--force"])
            self.assertEqual(status, expected)
            self.assertEqual(json.loads(stdout), result)
            self.assertEqual(bool(stderr), outcome == "uncertain")
            close.assert_called_once_with("target", force=True)

    def test_missing_target_is_an_error(self):
        with patch.object(tabs.sys, "platform", "darwin"), \
                patch.object(tabs, "close_tab", side_effect=RuntimeError("missing target")):
            status, stdout, stderr = self.invoke(["close", "--tab-id", "missing"])
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("missing target", stderr)

    def test_ungroup_requires_both_explicit_ids(self):
        for argv in (["ungroup", "--tab-id", "target"],
                     ["ungroup", "--tab-id", "target", "--group-id", "\n"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tabs.parse_args(argv)

    def test_ungroup_dry_run_does_not_connect(self):
        with patch.object(tabs.sys, "platform", "linux"), patch.object(tabs, "ungroup_tab") as ungroup:
            status, stdout, _ = self.invoke(["ungroup", "--tab-id", "target", "--group-id", "group", "--dry-run"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["ungroup"], "dry-run")
        ungroup.assert_not_called()

    def test_routes_ungroup_and_reports_uncertainty(self):
        with patch.object(tabs.sys, "platform", "darwin"), patch.object(tabs, "ungroup_tab", return_value={
                "ungroup": "uncertain", "warning": "refresh failed"}) as ungroup:
            status, _, stderr = self.invoke(["ungroup", "--tab-id", "target", "--group-id", "group"])
        self.assertEqual(status, 3)
        self.assertIn("refresh failed", stderr)
        ungroup.assert_called_once_with("target", "group")


if __name__ == "__main__":
    unittest.main()
