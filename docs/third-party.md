# 第三方来源

## 运行依赖

准确版本见根目录 `uv.lock`。

| 组件 | 用途 | 来源 / 许可 |
| --- | --- | --- |
| Python 3.12 | 运行环境 | [Python](https://www.python.org/)，PSF License |
| PySide6 / Qt | 原生窗口、WebEngine、音频 | [Qt for Python](https://doc.qt.io/qtforpython-6/)，LGPLv3 / GPLv3 / 商业许可；本项目使用未修改的动态库 |
| Fugashi | MeCab 日语形态分析 | [polm/fugashi](https://github.com/polm/fugashi)，MIT |
| UniDic Lite | 日语词典 | [polm/unidic-lite](https://github.com/polm/unidic-lite)，词库使用其原始 BSD / GPL / LGPL 许可说明 |
| pykakasi | 未登录词常用读音回退 | [miurahr/pykakasi](https://github.com/miurahr/pykakasi)，GPLv3 |
| cmudict / CMUdict | 英语词典发音 | [cmusphinx/cmudict](https://github.com/cmusphinx/cmudict)，BSD 风格许可 |
| PyWinRT | Windows 系统媒体会话 | [pywinrt](https://github.com/pywinrt/pywinrt)，MIT |
| Requests | 网络请求 | [psf/requests](https://github.com/psf/requests)，Apache 2.0 |
| websocket-client | 网易云本机 CDP 通道 | [websocket-client](https://github.com/websocket-client/websocket-client)，Apache 2.0 |
| uv | 项目私有依赖安装 | [astral-sh/uv](https://github.com/astral-sh/uv)，MIT / Apache 2.0 |

项目源码采用 GPLv3，见根目录 `LICENSE`。Windows 便携包的 `THIRD-PARTY-LICENSES/` 包含依赖许可原文与版本清单。Qt 使用独立动态库，位于 `_internal/`，未修改其实现。源码与构建脚本在 [项目仓库](https://github.com/AsaMisogi/Cloudmusic-Lyrics-Singing) 提供；第三方组件仍按各自许可分发。

## 资源服务

- 网易云公开搜索、歌词、公开音频播放接口：`music.163.com`。歌曲和歌词版权归各自权利人。
- 有道日汉、英汉词义查询：`dict.youdao.com`，界面注明词典来源。
- Google 翻译：`translate.googleapis.com`，由用户主动点击补译。
- MyMemory：[API 说明](https://mymemory.translated.net/doc/spec.php)，Google 不可用时的备用机译服务，有访问与配额限制。
- Windows 系统媒体会话：[Microsoft 文档](https://learn.microsoft.com/en-us/uwp/api/windows.media.control)。
- 本机连接参考：[Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)；[NeteaseHookSDK](https://github.com/lgnorant-lu/NeteaseHookSDK) 用于确认客户端支持 CDP。项目没有安装其 DLL 或复制其实现，播放适配基于本机客户端组件实测。
- 高刷新率设置：[Qt WebEngine 调试参数文档](https://doc.qt.io/qt-6/qtwebengine-debugging.html)；`--disable-frame-rate-limit` 的效果由本项目真实 Qt 验收采样确认。

## 原创资产

- `assets/design-mockup.png`：按本项目需求，通过内置 imagegen 工具生成的界面设计稿。
- `assets/icon.svg`、`assets/landscape.svg`：为本项目绘制的矢量图标和默认封面。
- `samples/practice.lrc`、`practice.zh.lrc`：原创演示句子。
- `samples/practice.wav`：`scripts/create_sample.py` 合成的原创提示音轨，没有使用第三方歌曲录音。
