"""GitHub 正式版本检查；只读取发布信息，不下载或替换程序文件。"""

import re
import logging
from urllib.parse import quote, urljoin, urlsplit, unquote

import requests

from . import __version__

REPOSITORY_URL = "https://github.com/AsaMisogi/Cloudmusic-Lyrics-Singing"
RELEASES_URL = REPOSITORY_URL + "/releases/latest"
LATEST_API = "https://api.github.com/repos/AsaMisogi/Cloudmusic-Lyrics-Singing/releases/latest"
LOG = logging.getLogger(__name__)


def version_tuple(value: str) -> tuple[int, int, int]:
    """项目正式版本固定为 v主.次.修订；数值比较避免 0.10 小于 0.9。"""
    if not isinstance(value, str) or not re.fullmatch(r"v?\d{1,6}\.\d{1,6}\.\d{1,6}", value):
        raise ValueError("发布版本号格式无法识别")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def _api_tag(current: str) -> str:
    """首选官方 API；保留正式版语义，失败交由官网入口再次确认。"""
    with requests.get(
        LATEST_API,
        headers={"Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2026-03-10",
                 "User-Agent": f"Utatomo/{current}", "Cache-Control": "no-cache"},
        timeout=(3.05, 7), allow_redirects=False,
    ) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("发布接口返回了非预期响应")
        release = response.json()
    if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("发布信息不是正式版本")
    return release.get("tag_name")


def _website_tag(current: str) -> str:
    """读取官网 latest 的跳转头，不消耗匿名 API 配额，也不解析易变的 HTML。

    GET + stream 只需要响应头；不跟随跳转、不下载发布页正文。官网负责选择
    最新正式 Release；必须返回本仓库的 /releases/tag/ 地址才接受结果。
    不能把登录页、代理提示、其他仓库或外站的跳转当作新版本。
    """
    with requests.get(
        RELEASES_URL,
        headers={"User-Agent": f"Utatomo/{current}", "Cache-Control": "no-cache"},
        timeout=(3.05, 7), allow_redirects=False, stream=True,
    ) as response:
        response.raise_for_status()
        if response.status_code not in (301, 302, 303, 307, 308):
            raise ValueError("发布页没有返回最新正式版本的跳转")
        location = response.headers.get("Location", "")
    address = urlsplit(urljoin(RELEASES_URL, location))
    prefix = urlsplit(REPOSITORY_URL).path + "/releases/tag/"
    if (address.scheme != "https" or address.netloc != "github.com"
            or address.query or address.fragment or not address.path.startswith(prefix)):
        raise ValueError("发布页跳转不是本仓库的正式版本地址")
    return unquote(address.path[len(prefix):])


def check_update(current: str = __version__) -> dict:
    """独立检查 API 与官网入口，任何一路成功即可确认版本。

    沿用 requests 的环境 / Windows 系统代理发现和证书设置，不关闭 TLS
    验证、不借助第三方镜像、不要求登录。每个入口只尝试一次且设置超时，
    网络操作保持在工作线程。两路都失败时明确报告无法确认，绝不假报最新。
    """
    for source, get_tag in (("GitHub API", _api_tag), ("GitHub 发布页", _website_tag)):
        try:
            tag = get_tag(current)
            latest = version_tuple(tag)
            return {"status": "available" if latest > version_tuple(current) else "current",
                    "version": tag.removeprefix("v"), "current": current,
                    "url": REPOSITORY_URL + "/releases/tag/" + quote(tag, safe="")}
        except (requests.RequestException, ValueError, TypeError) as exc:
            # 仅记录错误类型，避免代理异常文本中的地址或凭据进入日志。
            LOG.info("%s 检查未完成：%s", source, type(exc).__name__)
    return {"status": "error", "message": "暂时无法确认最新版本：GitHub 发布接口和发布页均不可用或返回异常。请检查网络或代理设置后重试，也可直接查看发布页。"}
