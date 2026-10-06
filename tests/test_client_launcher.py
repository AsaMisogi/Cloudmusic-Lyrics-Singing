"""离线验证路径持久化、重启授权与进程边界，不结束用户的真实进程。"""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import psutil

from utatomo import client_launcher as launcher
from utatomo.app import Bridge


class ClientLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "网易云 音乐"
        self.directory.mkdir()
        self.exe = self.directory / "cloudmusic.exe"
        self.exe.touch()

    def settings(self):
        with patch.object(launcher, "detect_client", return_value=self.exe):
            return launcher.ClientSettings(self.root / "data")

    def test_directory_and_quoted_executable_normalize(self):
        self.assertEqual(launcher.client_executable(self.directory), self.exe.resolve())
        self.assertEqual(launcher.client_executable(f'"{self.exe}"'), self.exe.resolve())
        for value in ("", str(self.root), str(self.root / "other.exe")):
            with self.assertRaises(ValueError):
                launcher.client_executable(value)

    def test_first_run_prefills_but_requires_confirmation_then_persists(self):
        settings = self.settings()
        self.assertFalse(settings.confirmed)
        self.assertEqual(settings.directory, str(self.directory))
        self.assertFalse(settings.file.exists())
        settings.save(str(self.exe))
        with patch.object(launcher, "detect_client") as detect:
            restored = launcher.ClientSettings(settings.file.parent)
        detect.assert_not_called()
        self.assertTrue(restored.confirmed)
        self.assertEqual(restored.directory, str(self.directory.resolve()))

    def test_invalid_save_keeps_previous_file_and_in_memory_settings(self):
        settings = self.settings()
        settings.save(str(self.directory))
        original = settings.file.read_bytes()
        with self.assertRaises(ValueError):
            settings.save(str(self.root))
        self.assertEqual(settings.file.read_bytes(), original)
        self.assertEqual(settings.directory, str(self.directory.resolve()))

    def test_write_failure_preserves_previous_settings(self):
        settings = self.settings()
        with patch.object(Path, "replace", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "保存失败"):
                settings.save(str(self.directory))
        self.assertFalse(settings.confirmed)

    def test_corrupt_configuration_reopens_setup(self):
        data = self.root / "data"
        data.mkdir()
        (data / "settings.json").write_text("{", encoding="utf-8")
        self.assertFalse(self.settings().confirmed)

    def test_saved_missing_directory_is_not_silently_replaced(self):
        settings = self.settings()
        settings.save(str(self.directory))
        self.exe.unlink()
        with patch.object(launcher, "detect_client") as detect:
            restored = launcher.ClientSettings(settings.file.parent)
        detect.assert_not_called()
        self.assertEqual(restored.directory, str(self.directory.resolve()))
        with self.assertRaises(ValueError):
            launcher.client_executable(restored.directory)

    def test_save_preserves_other_settings(self):
        settings = self.settings()
        settings.values["futurePreference"] = True
        settings.save(str(self.directory))
        self.assertTrue(json.loads(settings.file.read_text(encoding="utf-8"))["futurePreference"])

    def test_detection_prefers_running_custom_installation(self):
        process = Mock()
        process.exe.return_value = str(self.exe)
        with patch.object(launcher, "running_clients", return_value=[process]):
            self.assertEqual(launcher.detect_client(), self.exe.resolve())

    def test_other_installation_and_access_denied_are_not_closed(self):
        process = Mock()
        process.exe.return_value = str(self.root / "another/cloudmusic.exe")
        with patch.object(launcher, "running_clients", return_value=[process]):
            with self.assertRaisesRegex(ValueError, "与设置路径不同"):
                launcher.matching_processes(self.exe.resolve())
            process.exe.side_effect = psutil.AccessDenied(123)
            with self.assertRaisesRegex(ValueError, "手动完整退出"):
                launcher.matching_processes(self.exe.resolve())
        process.terminate.assert_not_called()

    def test_vanished_process_is_ignored(self):
        process = Mock()
        process.exe.side_effect = psutil.NoSuchProcess(123)
        with patch.object(launcher, "running_clients", return_value=[process]):
            self.assertEqual(launcher.matching_processes(self.exe.resolve()), [])

    def test_running_instance_requires_confirmation_without_side_effects(self):
        process = Mock()
        with patch.object(launcher, "matching_processes", return_value=[process]), \
                patch.object(launcher, "request_close") as close, \
                patch.object(launcher.subprocess, "Popen") as start:
            self.assertTrue(launcher.launch_client(str(self.directory))["confirmation"])
        close.assert_not_called()
        process.terminate.assert_not_called()
        start.assert_not_called()

    def test_confirmed_restart_waits_then_terminates_remaining_and_launches(self):
        process = Mock()
        with patch.object(launcher, "matching_processes", side_effect=[[process], [process], []]), \
                patch.object(launcher, "request_close") as close, \
                patch.object(launcher.psutil, "wait_procs", side_effect=[([], [process]), ([process], [])]) as wait, \
                patch.object(launcher.subprocess, "Popen") as start:
            self.assertFalse(launcher.launch_client(str(self.directory), restart=True)["confirmation"])
        close.assert_called_once_with([process])
        process.terminate.assert_called_once()
        self.assertEqual(wait.call_count, 2)
        args = start.call_args.args[0]
        self.assertEqual(args[0], str(self.exe.resolve()))
        self.assertIn("--remote-debugging-address=127.0.0.1", args)

    def test_graceful_exit_does_not_force_terminate(self):
        process = Mock()
        with patch.object(launcher, "matching_processes", side_effect=[[process], [process], []]), \
                patch.object(launcher, "request_close"), \
                patch.object(launcher.psutil, "wait_procs", return_value=([process], [])), \
                patch.object(launcher.subprocess, "Popen"):
            launcher.launch_client(str(self.directory), restart=True)
        process.terminate.assert_not_called()

    def test_no_launch_if_exit_fails(self):
        process = Mock()
        with patch.object(launcher, "matching_processes", return_value=[process]), \
                patch.object(launcher, "request_close"), \
                patch.object(launcher.psutil, "wait_procs", return_value=([], [process])), \
                patch.object(launcher.subprocess, "Popen") as start:
            with self.assertRaisesRegex(ValueError, "尚未完全退出"):
                launcher.launch_client(str(self.directory), restart=True)
        start.assert_not_called()

    def test_process_appearing_between_prepare_and_launch_requires_confirmation(self):
        with patch.object(launcher, "matching_processes", side_effect=[[], [Mock()]]), \
                patch.object(launcher.subprocess, "Popen") as start:
            self.assertTrue(launcher.launch_client(str(self.directory))["confirmation"])
        start.assert_not_called()

    def test_restart_confirmation_is_single_use_and_cancel_does_not_launch(self):
        bridge = SimpleNamespace(client_confirmation=str(self.directory),
                                 _finish_client_connection=Mock(), _work=Mock(), send=Mock())
        Bridge._action(bridge, "confirmClientRestart", False)
        self.assertIsNone(bridge.client_confirmation)
        bridge._finish_client_connection.assert_called_once()
        Bridge._action(bridge, "confirmClientRestart", True)
        bridge._work.assert_not_called()

    def test_repeat_connect_click_is_ignored(self):
        bridge = SimpleNamespace(client_busy=True, send=Mock(), _work=Mock())
        Bridge._launch_cloud(bridge)
        bridge._work.assert_not_called()

    def test_connection_timeout_and_success_clear_busy_state(self):
        bridge = SimpleNamespace(cloud_state={"transport": "smtc"}, client_deadline=0,
                                 _finish_client_connection=Mock(), send=Mock())
        Bridge._check_client_connection(bridge)
        bridge._finish_client_connection.assert_called_once()
        self.assertEqual(bridge.send.call_args.args[0], "error")
        bridge.cloud_state = {"transport": "client"}
        Bridge._check_client_connection(bridge)
        self.assertEqual(bridge.send.call_args.args[0], "notice")


if __name__ == "__main__":
    unittest.main()
