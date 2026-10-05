"""只读诊断 Windows 媒体会话，不改变播放状态。"""

import asyncio
import json

from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager


async def main():
    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    for session in manager.get_sessions():
        media = await session.try_get_media_properties_async()
        timeline = session.get_timeline_properties()
        info = session.get_playback_info()
        print(
            json.dumps(
                {
                    "app": session.source_app_user_model_id,
                    "title": media.title,
                    "artist": media.artist,
                    "position": str(timeline.position),
                    "end": str(timeline.end_time),
                    "updated": str(timeline.last_updated_time),
                    "status": str(info.playback_status),
                    "seek": info.controls.is_playback_position_enabled,
                },
                ensure_ascii=False,
            )
        )


asyncio.run(main())
