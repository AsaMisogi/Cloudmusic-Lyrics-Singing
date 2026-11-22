"""只替换 HTTP 传输；文件大小、摘要、线路回退和桌面显示选择使用实际逻辑。"""
import hashlib
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from utatomo.desktop import DEFAULT, desktop_line
from utatomo.portable_updates import fetch, receive_asset, PROXY


class DesktopContentTests(unittest.TestCase):
    def test_gaps_seek_and_new_song(self):
        lines = [{"text": "甲"}, {"text": ""}, {"text": "　"}, {"text": "乙"}, {"text": ""}]
        for index, expected in [(0, 0), (2, 0), (4, 3), (1, 0), (-1, -1)]:
            self.assertEqual(desktop_line(lines, index, DEFAULT)[0], expected)
        self.assertFalse(any(desktop_line([{"text": ""}], 0, DEFAULT)[1]))

    def test_uses_only_selected_layers(self):
        lines = [{"text": "a", "translation": "甲", "segments": {"roman": "te"}},
                 {"text": "b"}, {"translation": "丙", "text": ""}]
        self.assertEqual(desktop_line(lines, 1, dict(DEFAULT, original=False, reading=False))[1][2], "甲")
        self.assertEqual(desktop_line(lines, 2, dict(DEFAULT, original=False, reading=False))[0], 2)
        self.assertEqual(desktop_line(lines, 2, dict(DEFAULT, original=False, translation=False,
                                                       reading=True, roman=True))[1][1], "te")
        self.assertEqual(desktop_line(lines, 1, DEFAULT)[0], 1)


class Response(io.BytesIO):
    def geturl(self):
        return "https://test.invalid/file"


class RouteTests(unittest.TestCase):
    def test_integrity_failure_restarts_on_github_only_in_auto_mode(self):
        url = "https://github.com/example/release.zip"
        good = b"content"
        a = {"size": len(good), "sha256": hashlib.sha256(good).hexdigest()}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "file"
            def read(r, label):
                receive_asset(r, out, a, label, lambda *_: None, threading.Event())
            with patch("utatomo.portable_updates.urlopen", side_effect=[Response(b"corrupt"), Response(good)]) as get:
                fetch(url, "auto", read, lambda *_: None)
                self.assertEqual([c.args[0].full_url for c in get.call_args_list], [PROXY + url, url])
                self.assertEqual(out.read_bytes(), good)
            for source, prefix in [("mirror", PROXY), ("github", "")]:
                with patch("utatomo.portable_updates.urlopen", return_value=Response(b"short")) as get:
                    with self.assertRaisesRegex(ValueError, "更换下载源"):
                        fetch(url, source, read, lambda *_: None)
                    self.assertEqual([c.args[0].full_url for c in get.call_args_list], [prefix + url])


if __name__ == "__main__":
    unittest.main()
