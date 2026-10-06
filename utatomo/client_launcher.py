"""网易云安装路径、便携配置和经用户确认的客户端重启。

此模块不依赖 Qt，耗时的进程枚举、退出等待由控制器放到工作线程。
只处理名称与完整路径均匹配的 cloudmusic.exe，不按镜像名批量杀进程。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import psutil

LOG = logging.getLogger(__name__)


def client_executable(value: str | Path) -> Path:
    """接受安装目录或主程序；保存前检查真实文件，统一返回绝对路径。"""
    text = str(value).strip().strip('"')
    if not text:
        raise ValueError("请选择网易云音乐所在的文件夹。")
    path = Path(os.path.expandvars(text)).expanduser()
    if path.is_dir():
        path /= "cloudmusic.exe"
    if path.name.lower() != "cloudmusic.exe" or not path.is_file():
        raise ValueError("此路径下没有 cloudmusic.exe，请选择网易云音乐安装目录或主程序。")
    return path.resolve()


def running_clients() -> list[psutil.Process]:
    """每次重新枚举，避免 process_iter 缓存保留已被复用的 PID 身份。"""
    psutil.process_iter.cache_clear()
    return [p for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower() == "cloudmusic.exe"]


def detect_client() -> Path | None:
    """运行中的安装优先；再查 Windows App Paths / 卸载项和常见目录。

    注册表只提供候选路径，绝不执行其中的命令。每个候选都经过文件校验，
    因此旧卸载记录、失效路径或不可读进程不会阻止用户手动选择。
    """
    candidates = []
    for process in running_clients():
        try:
            candidates.append(process.exe())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if sys.platform == "win32":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                for key, field in (
                    (r"Software\Microsoft\Windows\CurrentVersion\App Paths\cloudmusic.exe", ""),
                    (r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CloudMusic", "InstallLocation"),
                    (r"Software\Microsoft\Windows\CurrentVersion\Uninstall\网易云音乐", "InstallLocation"),
                ):
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                            value, _ = winreg.QueryValueEx(handle, field)
                            if isinstance(value, str):
                                candidates.append(value)
                    except OSError:
                        continue
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramW6432"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / "NetEase/CloudMusic")
    for candidate in candidates:
        try:
            return client_executable(candidate)
        except (ValueError, OSError):
            continue
    return None


class ClientSettings:
    """首次引导以成功保存为完成标记；取消引导仍可使用本地练唱。

    自动发现只预填，不静默确认。已保存但失效的目录保留给用户修正，
    不擅自改用另一份安装。写入采用同目录原子替换，失败时保留旧配置。
    """

    def __init__(self, data: Path):
        self.file = data / "settings.json"
        self.values = {}
        try:
            values = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(values, dict):
                self.values = values
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            LOG.warning("客户端设置不可读，将重新显示路径引导。", exc_info=True)
        saved = self.values.get("cloudMusicDirectory")
        self.confirmed = isinstance(saved, str) and bool(saved.strip())
        detected = None if self.confirmed else detect_client()
        self.directory = saved if self.confirmed else str(detected.parent) if detected else ""

    def save(self, value: str) -> None:
        exe = client_executable(value)
        values = {**self.values, "cloudMusicDirectory": str(exe.parent)}
        self.file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.file)
        except OSError as exc:
            raise ValueError("路径保存失败，请检查软件所在目录的写入权限。") from exc
        self.values, self.directory, self.confirmed = values, str(exe.parent), True


def matching_processes(exe: Path) -> list[psutil.Process]:
    """发现另一安装实例或无读取权限时停止，避免重启到错误客户端。"""
    matches = []
    for process in running_clients():
        try:
            actual = Path(process.exe()).resolve()
            if actual != exe:
                raise ValueError(f"正在运行的网易云位于 {actual.parent}，与设置路径不同。请先在设置中选择该目录，或完整退出该客户端。")
            matches.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise ValueError("无法读取网易云进程。请手动完整退出网易云后重新连接。") from exc
    return matches


def prepare_client(directory: str) -> dict:
    exe = client_executable(directory)
    return {"exe": exe, "running": bool(matching_processes(exe))}


def request_close(processes: list[psutil.Process]) -> None:
    """向该安装实例的顶层窗口请求关闭，包括隐藏的托盘窗口。

    WM_CLOSE 可能只把网易云缩到托盘，所以控制器说明会结束后台进程。
    PostMessage 是异步请求，不让无响应的客户端阻塞工作线程。
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    by_pid = {p.pid: p for p in processes}

    @callback_type
    def close_window(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = by_pid.get(pid.value)
        if process and process.is_running():
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return True

    user32.EnumWindows(close_window, 0)


def launch_client(directory: str, restart: bool = False) -> dict:
    """执行前再次校验路径和进程；只有明确确认过的请求允许结束进程。

    检查后才出现的实例也需要弹窗，不能因检测与启动之间的竞态跳过确认。
    psutil 的 terminate 校验进程身份，避免 PID 复用后结束无关进程。
    """
    plan = prepare_client(directory)
    exe = plan["exe"]
    processes = matching_processes(exe)
    if processes and not restart:
        return {"confirmation": True, "directory": str(exe.parent)}
    try:
        if processes:
            request_close(processes)
            _, alive = psutil.wait_procs(processes, timeout=4)
            for process in alive:
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(alive, timeout=5)
            if alive or matching_processes(exe):
                raise ValueError("网易云尚未完全退出，请从托盘完整退出后重试连接。")
        subprocess.Popen(
            [str(exe), "--remote-debugging-port=9222", "--remote-debugging-address=127.0.0.1"],
            cwd=str(exe.parent),
        )
    except psutil.AccessDenied as exc:
        raise ValueError("没有权限关闭网易云。请手动从托盘完整退出后重新连接。") from exc
    except OSError as exc:
        raise ValueError(f"网易云启动失败，请检查安装路径和执行权限：{exc}") from exc
    return {"confirmation": False}
