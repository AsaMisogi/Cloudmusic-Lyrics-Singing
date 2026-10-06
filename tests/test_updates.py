"""离线验证版本判断、GitHub 失败反馈与应用级更新任务的生命周期。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from utatomo.app import Bridge
from utatomo.updates import check_update, version_tuple, REPOSITORY_URL, RELEASES_URL


class UpdateTests(unittest.TestCase):
    def response(self, tag="v0.3.0", status=200, **fields):
        response = Mock(status_code=status)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.json.return_value = {"tag_name": tag, "draft": False, "prerelease": False, **fields}
        return response

    def test_numeric_versions(self):
        self.assertGreater(version_tuple("v0.10.0"), version_tuple("0.9.9"))
        for tag in (None, "latest", "v1.2", "v1.2.3-rc.1", "1.2.3/evil", "1.2.3\n"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                version_tuple(tag)

    def test_new_equal_and_older_release(self):
        for tag, expected in (("v0.10.0", "available"), ("v0.3.0", "current"), ("0.2.1", "current")):
            with self.subTest(tag=tag), patch("utatomo.updates.requests.get", return_value=self.response(tag)) as get:
                result = check_update("0.3.0")
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["url"], REPOSITORY_URL + "/releases/tag/" + tag)
                self.assertFalse(get.call_args.kwargs["allow_redirects"])
                self.assertEqual(get.call_args.kwargs["timeout"], (3.05, 7))

    def test_untrusted_release_link_is_not_used(self):
        with patch("utatomo.updates.requests.get", return_value=self.response(html_url="https://evil.example/")):
            self.assertTrue(check_update("0.2.1")["url"].startswith(REPOSITORY_URL))

    def test_invalid_or_nonstable_release(self):
        for response in (self.response("v0.4.0-rc.1"), self.response(draft=True),
                         self.response(prerelease=True), self.response(status=302)):
            with self.subTest(response=response), patch("utatomo.updates.requests.get", return_value=response):
                self.assertEqual(check_update()["status"], "error")
        response = self.response()
        for data in ([], None, {"tag_name": "v0.4.0"}):
            response.json.return_value = data
            with patch("utatomo.updates.requests.get", return_value=response):
                self.assertEqual(check_update()["status"], "error")

    def test_network_and_http_errors(self):
        for error in (requests.Timeout(), requests.ConnectionError(), requests.exceptions.SSLError()):
            with patch("utatomo.updates.requests.get", side_effect=error):
                self.assertEqual(check_update()["status"], "error")
        for status in (403, 429, 404, 500):
            response = self.response(status=status)
            if status == 500:
                response.raise_for_status.side_effect = requests.HTTPError()
            with patch("utatomo.updates.requests.get", return_value=response):
                self.assertEqual(check_update()["status"], "error")
        response = self.response()
        response.json.side_effect = ValueError("malformed JSON")
        with patch("utatomo.updates.requests.get", return_value=response):
            self.assertEqual(check_update()["status"], "error")

    def website(self, location=None, status=302):
        response = self.response(status=status)
        response.headers = {"Location": location or REPOSITORY_URL + "/releases/tag/v0.3.0"}
        return response

    def test_rate_limit_and_http_failure_fall_back_to_website(self):
        for status in (403, 429, 404, 500):
            with self.subTest(status=status), patch("utatomo.updates.requests.get", side_effect=[
                    self.response(status=status), self.website()]) as get:
                result = check_update("0.2.1")
                self.assertEqual(result["status"], "available")
                self.assertEqual(result["version"], "0.3.0")
                self.assertEqual(get.call_count, 2)
                self.assertEqual(get.call_args.args[0], RELEASES_URL)
                self.assertTrue(get.call_args.kwargs["stream"])
                self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_timeout_tls_and_proxy_failure_can_recover_on_other_host(self):
        for error in (requests.Timeout(), requests.exceptions.SSLError(), requests.exceptions.ProxyError()):
            with self.subTest(error=error), patch("utatomo.updates.requests.get", side_effect=[error, self.website()]):
                self.assertEqual(check_update()["status"], "current")

    def test_invalid_api_payload_can_recover_via_website(self):
        for response in (self.response("unknown"), self.response(prerelease=True), self.response(draft=True)):
            with patch("utatomo.updates.requests.get", side_effect=[response, self.website()]):
                self.assertEqual(check_update()["status"], "current")
        response = self.response()
        response.json.side_effect = ValueError("invalid JSON")
        with patch("utatomo.updates.requests.get", side_effect=[response, self.website()]):
            self.assertEqual(check_update()["status"], "current")

    def test_website_relative_url_numeric_comparison_and_old_version(self):
        for tag, expected in (("v0.10.0", "available"), ("0.3.0", "current"), ("v0.2.1", "current")):
            with self.subTest(tag=tag), patch("utatomo.updates.requests.get", side_effect=[
                    requests.ConnectionError(), self.website("/AsaMisogi/Cloudmusic-Lyrics-Singing/releases/tag/" + tag)]):
                self.assertEqual(check_update()["status"], expected)

    def test_website_rejects_login_proxy_external_and_nonstable_redirects(self):
        for location in ("https://evil.example/releases/tag/v9.0.0", "https://github.com/other/repo/releases/tag/v9.0.0",
                         REPOSITORY_URL + "/releases/tag/v0.4.0-rc.1", REPOSITORY_URL + "/releases/tag/v0.4.0/extra",
                         REPOSITORY_URL + "/releases/tag/v0.4.0?redirect=evil", "http://github.com/login",
                         "https://github.com/login", "https://user@github.com/AsaMisogi/Cloudmusic-Lyrics-Singing/releases/tag/v0.4.0",
                         REPOSITORY_URL + "/releases/tag/%2Fv0.4.0", REPOSITORY_URL + "/releases/tag/v0.4.0#fragment"):
            with self.subTest(location=location), patch("utatomo.updates.requests.get", side_effect=[
                    requests.Timeout(), self.website(location)]):
                self.assertEqual(check_update()["status"], "error")
        for status in (200, 403, 429, 404, 500):
            with patch("utatomo.updates.requests.get", side_effect=[requests.Timeout(), self.website(status=status)]):
                self.assertEqual(check_update()["status"], "error")

    def test_offline_does_not_report_latest_and_does_not_loop(self):
        with patch("utatomo.updates.requests.get", side_effect=requests.ConnectionError()) as get:
            result = check_update()
            self.assertEqual(result["status"], "error")
            self.assertIn("网络或代理", result["message"])
            self.assertEqual(get.call_count, 2)

    def bridge(self):
        return SimpleNamespace(closing=False, update_manual=False, update_busy=False,
                               update_url="", update_pool=Mock(), send=Mock(), _work=Mock())

    def test_duplicate_manual_request_joins_startup_check(self):
        bridge = self.bridge()
        Bridge._check_update(bridge, manual=False)
        Bridge._check_update(bridge)
        self.assertTrue(bridge.update_manual)
        bridge._work.assert_called_once()
        Bridge._finish_update(bridge, {"status": "current"})
        self.assertFalse(bridge.update_busy)
        self.assertFalse(bridge.update_manual)
        bridge.send.assert_called_with("updateResult", {"status": "current", "manual": True})

    def test_automatic_check_is_quiet_except_new_version(self):
        for status in ("current", "error", "available"):
            bridge = self.bridge()
            data = {"status": status, "message": "失败", "url": REPOSITORY_URL + "/releases/tag/v0.4.0"}
            Bridge._finish_update(bridge, data)
            result_calls = [c for c in bridge.send.call_args_list if c.args[0] == "updateResult"]
            self.assertEqual(len(result_calls), int(status == "available"))
            self.assertEqual(bool(bridge.update_url), status == "available")

    def test_close_ignores_requests_and_late_results(self):
        bridge = self.bridge()
        bridge.closing = True
        Bridge._check_update(bridge)
        Bridge._finish_update(bridge, {"status": "available"})
        bridge._work.assert_not_called()
        bridge.send.assert_not_called()

    def test_browser_only_uses_backend_release(self):
        bridge = self.bridge()
        bridge.update_url = REPOSITORY_URL + "/releases/tag/v0.4.0"
        bridge._open_project_url = Mock()
        Bridge._action(bridge, "openUpdate", "https://evil.example")
        bridge._open_project_url.assert_called_once_with(bridge.update_url)

    def test_update_task_survives_song_change(self):
        bridge = self.bridge()
        bridge.launch_pool = Mock()
        bridge.pending = []
        bridge.incoming = Mock()
        Bridge._work(bridge, bridge.update_pool, "update", lambda: {})
        self.assertEqual(bridge.pending, [])

    def test_initialize_checks_only_once_after_ui_ready(self):
        bridge = self.bridge()
        bridge.mode = "cloud"
        bridge.metadata = {}
        bridge.cloud_state = {}
        bridge.client_settings = SimpleNamespace(confirmed=True)
        bridge.client_busy = False
        bridge.lines = []
        bridge.update_started = False
        bridge._send_client_settings = Mock()
        bridge._send_versions = Mock()
        bridge._check_update = Mock()
        with patch("utatomo.app.sys.argv", ["main.py"]):
            Bridge.initialize(bridge)
            Bridge.initialize(bridge)
        self.assertTrue(bridge.ready)
        bridge._check_update.assert_called_once_with(manual=False)


if __name__ == "__main__":
    unittest.main()
