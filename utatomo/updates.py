"""GitHub 正式版本检查；只读取发布信息，不下载或替换程序文件。"""

import re
from urllib.parse import quote

import requests

from . import __version__

REPOSITORY_URL = "https://github.com/AsaMisogi/Cloudmusic-Lyrics-Singing"
RELEASES_URL = REPOSITORY_URL + "/releases/latest"
LATEST_API = "https://api.github.com/repos/AsaMisogi/Cloudmusic-Lyrics-Singing/releases/latest"


def version_tuple(value: str) -> tuple[int, int, int]:
    """项目正式版本固定为 v主.次.修订；数值比较避免 0.10 小于 0.9。"""
    if not isinstance(value, str) or not re.fullmatch(r"v?\d{1,6}\.\d{1,6}\.\d{1,6}", value):
        raise ValueError("发布版本号格式无法识别")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def check_update(current: str = __version__) -> dict:
    """后台调用，返回适合界面显示的结果；失败不能伪装成已经是最新版。

    latest 接口由仓库维护者指定正式 Release，不追踪预发布或未发布标签。
    超时且不自动重试，避免离线启动长时间占用工作线程；TLS 使用默认验证。
    跳转地址由固定仓库和已验证的版本标签构造，不采用远端任意外链。
    """
    try:
        with requests.get(
            LATEST_API,
            headers={"Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2026-03-10",
                     "User-Agent": f"Utatomo/{current}"},
            timeout=(3.05, 7), allow_redirects=False,
        ) as response:
            if response.status_code in (403, 429):
                return {"status": "error", "message": "GitHub 暂时限制了请求，请稍后重试，或直接查看发布页。"}
            if response.status_code == 404:
                return {"status": "error", "message": "未找到可用的正式版本，请直接查看 GitHub 发布页。"}
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("发布接口返回了非预期响应")
            release = response.json()
        if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
            raise ValueError("发布信息不是正式版本")
        tag = release.get("tag_name")
        latest = version_tuple(tag)
        return {"status": "available" if latest > version_tuple(current) else "current",
                "version": tag.removeprefix("v"), "current": current,
                "url": REPOSITORY_URL + "/releases/tag/" + quote(tag, safe="")}
    except requests.RequestException:
        return {"status": "error", "message": "无法连接 GitHub，请检查网络后重试，或直接查看发布页。"}
    except (ValueError, TypeError):
        return {"status": "error", "message": "GitHub 发布信息无法识别，请稍后重试，或直接查看发布页。"}
