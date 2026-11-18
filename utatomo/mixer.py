"""只读写网易云进程的 Windows 音频会话，不改变设备主音量或其他应用。"""

import logging
from pathlib import Path

import psutil


def choose_session(sessions, directory, target=None):
    """首选正在出声的会话。写入须命中用户刚才看到的同一会话；切换设备时重新读取。"""
    matches = []
    for session in sessions:
        try:
            proc = session.Process
            if (
                not proc
                or proc.name().casefold() != "cloudmusic.exe"
                or session.State == 2
            ):
                continue
            if directory and Path(proc.exe()).parent != Path(directory):
                continue
            if target and target != session.InstanceIdentifier:
                continue
            matches.append(session)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return max(matches, key=lambda s: s.State, default=None)


def cloud_level(directory, target=None, percent=None):
    """在串行工作线程中短暂持有 COM 对象；只在打开音量或提交调节时枚举输出设备。"""
    import comtypes
    from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.utils import AudioSession, AudioUtilities

    def access():
        devices = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(
            EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value
        )
        sessions = []
        for i in range(devices.GetCount()):
            device = devices.Item(i)
            manager = device.Activate(
                IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None
            ).QueryInterface(IAudioSessionManager2)
            items = manager.GetSessionEnumerator()
            for j in range(items.GetCount()):
                ctl = items.GetSession(j)
                if ctl:
                    sessions.append(
                        AudioSession(ctl.QueryInterface(IAudioSessionControl2))
                    )
        session = choose_session(sessions, directory, target)
        if not session:
            return {"message": "请先在网易云播放音乐，再打开音量。"}
        level = session.SimpleAudioVolume
        if percent is not None:
            level.SetMasterVolume(percent / 100, None)
            if percent and level.GetMute():
                level.SetMute(False, None)
        return {
            "percent": 0 if level.GetMute() else round(level.GetMasterVolume() * 100),
            "target": session.InstanceIdentifier,
        }

    comtypes.CoInitialize()
    try:
        return access()
    except (OSError, comtypes.COMError) as exc:
        logging.getLogger(__name__).info("无法读取应用音量：%s", exc)
        return {"message": "当前输出设备未提供应用音量，请在网易云中调节。"}
    finally:
        comtypes.CoUninitialize()
