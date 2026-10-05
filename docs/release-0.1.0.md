# 咏伴 0.1.0

首个 Windows x64 便携版。

- 跟随网易云播放显示日语、英语歌词，支持客户端双向播放和进度控制。
- 原文、假名 / IPA 和中文译文同时显示，支持查词和歌曲内注音修正。
- 本地音频支持变速、点击歌词跳转、单句循环和 A/B 循环。
- 支持切换歌词版本、导入歌词、调整字号和时间偏移。

下载 `Utatomo-0.1.0-windows-x64.zip`，完整解压后运行 `Utatomo.exe`。无需安装 Python；请保留 `_internal` 文件夹。系统要求 Windows 10 / 11 x64。

客户端同步模式暂不支持变速，进度精度取决于网易云客户端。日语特殊唱法可能需要手动修正。普通 LRC 的行内高亮为估算，机译会单独标记。

程序未做代码签名。`SHA256SUMS.txt` 提供下载文件校验值。使用步骤和实际截图见 [README](https://github.com/AsaMisogi/Cloudmusic-Lyrics-Singing#readme)，第三方许可附在便携包中。项目采用 GPLv3。
