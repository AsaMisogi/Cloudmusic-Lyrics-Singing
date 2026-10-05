"""离线验证新增播放语义、封面缓存与切歌隔离，不操作真实客户端。"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from utatomo.app import Bridge
from utatomo.media import CloudMedia
from utatomo.services import Services


class InteractionTests(unittest.TestCase):
    def test_lyric_seek_clears_outside_loop_and_requests_play(self):
        bridge = SimpleNamespace(loop_region=(1000, 2000), send=Mock(), _seek=Mock())
        Bridge._action(bridge, "seekAndPlay", 3000)
        self.assertIsNone(bridge.loop_region)
        bridge._seek.assert_called_once_with(3000, play=True)

    def test_local_seek_only_plays_when_requested(self):
        player = Mock()
        player.duration.return_value = 10000
        bridge = SimpleNamespace(mode="local", player=player)
        Bridge._seek(bridge, 5000)
        player.play.assert_not_called()
        Bridge._seek(bridge, 6000, play=True)
        player.setPosition.assert_called_with(6000)
        player.play.assert_called_once()

    def test_smtc_does_not_play_after_failed_seek(self):
        async def run():
            session = SimpleNamespace(
                try_change_playback_position_async=AsyncMock(return_value=False),
                try_play_async=AsyncMock(return_value=True),
            )
            media = SimpleNamespace(command_lock=asyncio.Lock(),
                                    client=SimpleNamespace(state=None), session=session)
            with self.assertRaises(ValueError):
                await CloudMedia._command(media, "seekAndPlay", 1000)
            session.try_play_async.assert_not_called()
            session.try_change_playback_position_async.return_value = True
            await CloudMedia._command(media, "seekAndPlay", 2000)
            session.try_change_playback_position_async.assert_called_with(20000000)
            session.try_play_async.assert_awaited_once()
        asyncio.run(run())

    def test_old_cover_does_not_replace_current_song(self):
        bridge = SimpleNamespace(generation=8, identity="new", mode="cloud",
                                 metadata={}, send=Mock())
        payload = {"generation": None, "kind": "cover", "data": "image",
                   "extra": {"identity": "old"}}
        Bridge._receive(bridge, "result", payload)
        bridge.send.assert_not_called()
        payload["extra"]["identity"] = "new"
        Bridge._receive(bridge, "result", payload)
        bridge.send.assert_called_once_with("cover", {"cover": "image"})

    def test_cover_normalizes_cdn_type_and_uses_offline_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Services(Path(directory))
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.headers = {"Content-Type": "image/jpg"}
            response.iter_content.return_value = [b"\x89PNG\r\n\x1a\nexample"]
            with patch.object(service, "request", return_value={"songs": [
                {"album": {"picUrl": "https://p1.music.126.net/test.png"}}
            ]}) as detail, patch("utatomo.services.requests.get", return_value=response) as download:
                cover = service.cover("123")
                self.assertTrue(cover.startswith("data:image/png;base64,"))
                self.assertEqual(service.cover("123"), cover)
                detail.assert_called_once()
                download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
