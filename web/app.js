/* 轻量原生界面。Qt 是真实播放时钟；requestAnimationFrame 仅在两次状态快照间平滑显示。
 * 所有歌词、在线词典文字使用 textContent，避免外部文本被当作 HTML 执行。
 */
"use strict";
const $ = (id) => document.getElementById(id);
const playbackClock = new PlaybackClock();
const state = {
  mode: "cloud",
  lines: [],
  lyricSource: "",
  position: 0,
  duration: 0,
  playing: false,
  rate: 1,
  canSeek: false,
  canRate: false,
  hasTimeline: true,
  sampled: performance.now(),
  active: -1,
  dragging: false,
  follow: true,
  playOnLyricSeek: true,
  resumeAfterBrowse: false,
  followMode: "advance",
  resumeFollowAt: 0,
  scrollTarget: null,
  pendingSeek: null,
  dict: false,
  token: null,
  loop: null,
  a: null,
  offset: 0,
};
window.__errors = [];
window.addEventListener("error", (e) => window.__errors.push(e.message));
let toastTimer,
  lastRenderActive = -2;
let lyricRows = [], activeTokens = [], previousFrame = 0;
function action(name, value = null) {
  if (window.backend) window.backend.action(name, JSON.stringify(value));
  else toast("请通过项目中的启动.bat 打开桌面版。", true);
}
function toast(message, error = false, persist = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  if (!persist)
    toastTimer = setTimeout(
      () => ($("toast").hidden = true),
      error ? 6500 : 2800,
    );
}
function time(ms) {
  ms = Math.max(0, Math.floor(ms || 0));
  return `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
function estimatedPosition() {
  if (!state.hasTimeline) return 0;
  return playbackClock.read(performance.now());
}
function seek(ms, fromLyric = false) {
  if (!state.canSeek) {
    toast("当前播放器没有开放跳转；本地歌曲支持精细定位。", true);
    return;
  }
  const position = Math.max(0, Math.min(state.duration, ms));
  action(fromLyric && state.playOnLyricSeek ? "seekAndPlay" : "seek", position);
  state.position = position;
  state.sampled = performance.now();
  playbackClock.seek(position, state.sampled);
  // 指令往返期间保留预览，避免旧快照把拖动后的滑块拉回原处。
  state.pendingSeek = {position, from: state.sampled, until: state.sampled + 1800};
  state.resumeFollowAt = 0;
  lastRenderActive = -2;
  $("followButton").hidden = true;
}
function currentIndex(position) {
  let low = 0,
    high = state.lines.length - 1,
    found = -1;
  while (low <= high) {
    let mid = (low + high) >> 1;
    const start = state.lines[mid].start;
    if (start === null) return -1;
    if (start <= position) {
      found = mid;
      low = mid + 1;
    } else high = mid - 1;
  }
  return found;
}
function lineEnd(index) {
  return (
    state.lines[index]?.end ?? state.lines[index + 1]?.start ?? state.duration
  );
}
function goLine(delta) {
  if (!state.lines.length) return;
  const i = Math.max(0, Math.min(state.lines.length - 1, state.active + delta));
  if (state.lines[i].start === null) {
    toast("这份歌词没有时间标签，仅支持阅读。");
    return;
  }
  seek(state.lines[i].start + state.offset);
}
function updatePlayback(data) {
  const now = performance.now();
  let force = false;
  if (state.pendingSeek) {
    const expected = state.pendingSeek.position + (data.playing ? now - state.pendingSeek.from : 0);
    if (Math.abs((data.position || 0) - expected) < 250 || now >= state.pendingSeek.until) {
      state.pendingSeek = null;
      force = true;
    } else data = {...data, position: estimatedPosition()};
  }
  playbackClock.update(data, now, force);
  Object.assign(state, {
    position: playbackClock.read(now),
    duration: data.duration || 0,
    playing: !!data.playing,
    rate: data.rate || 1,
    canSeek: !!data.canSeek,
    canRate: !!data.canRate,
    hasTimeline: data.hasTimeline !== false,
    sampled: performance.now(),
  });
  $("playGlyph").textContent = state.playing ? "Ⅱ" : "▶";
  $("play").setAttribute("aria-label", state.playing ? "暂停" : "播放");
  $("seek").disabled = !state.canSeek;
  $("seek").max = Math.max(1, state.duration);
  $("play").disabled = data.canPlay === false;
  $("duration").textContent = time(state.duration);
  $("speed").disabled = !state.canRate;
  $("speed").value = String(state.rate);
  for (const id of [
    "nudgeBack",
    "nudgeForward",
    "previousLine",
    "nextLine",
    "lineLoop",
    "setA",
    "setB",
  ])
    $(id).disabled = !state.canSeek;
}
function setMode(mode) {
  state.mode = mode;
  $("practiceButton").hidden = mode !== "cloud";
  $("connectCloud").hidden = mode !== "cloud";
  $("cloudMode").classList.toggle("selected", mode === "cloud");
  $("localMode").classList.toggle("selected", mode === "local");
  $("capabilityNotice").hidden = true;
  $("connectionLabel").textContent =
    mode === "local" ? "本地练唱 · 毫秒定位" : "正在连接网易云";
  $("connection").classList.toggle("online", mode === "local");
  if (mode === "local") state.hasTimeline = true;
}
function setDictionary(enabled) {
  state.dict = enabled;
  $("dictionaryToggle").checked = enabled;
  $("dictionaryPanel").hidden = !enabled;
  document.body.classList.toggle("dict-on", enabled);
  savePreferences();
}
function showWord(token) {
  state.token = token;
  $("dictEmpty").hidden = true;
  $("dictContent").hidden = false;
  $("dictWord").textContent = token.text;
  $("dictReading").textContent =
    token.reading || (token.language === "ja" ? token.text : "暂无词典音标");
  $("dictPos").textContent = token.pos || "词汇";
  $("dictDefinitions").textContent = "正在查询中文释义…";
  $("dictSource").textContent = token.source;
  action("dictionary", token);
}
function renderLyrics() {
  const fragment = document.createDocumentFragment();
  state.lines.forEach((line, index) => {
    const row = document.createElement("div");
    row.className = "lyric-line";
    row.tabIndex = 0;
    row.dataset.index = index;
    row.setAttribute("role", "button");
    row.setAttribute(
      "aria-label",
      `${line.start === null ? "" : time(line.start) + " "}${line.text || "间奏"}`,
    );
    const original = document.createElement("div");
    original.className = "lyric-original";
    let character = 0;
    (line.tokens || [{ text: line.text, reading: "" }]).forEach((token) => {
      const span = document.createElement("span");
      span.className =
        "token" +
        (token.reading ? " has-reading" : "") +
        (token.language === "en" ? " en" : "");
      span.dataset.start = character;
      character += token.text.length;
      span.dataset.end = character;
      span.dataset.clickable = !!token.language && !!token.text.trim();
      span.classList.toggle("reading-conflict", !!token.readingConflict);
      if (token.reading) span.title = `${token.reading} · ${token.source || "自动注音"}` +
        (token.readingConflict ? "\n读音有分歧，词典模式中可比较并修正：" +
          token.readingCandidates.map(c=>`${c.reading}（${c.source}）`).join(" / ") : "");
      // 将日语词尾已有的假名移出 ruby，注音准确落在汉字上方。
      // 词汇边界仍保持完整，点击「新しい」会查询同一个词。
      let partStart = Number(span.dataset.start);
      for (const part of rubyParts(token)) {
        const base = document.createElement("span");
        base.className = "token-base";
        base.dataset.start = partStart;
        partStart += part.text.length;
        base.dataset.end = partStart;
        base.textContent = part.text;
        if (part.reading) {
          const ruby = document.createElement("ruby");
          ruby.append(base);
          const rt = document.createElement("rt");
          rt.textContent = part.reading;
          ruby.append(rt);
          span.append(ruby);
        } else span.append(base);
      }
      span.addEventListener("click", (e) => {
        if (state.dict && !e.shiftKey && token.language) {
          e.stopPropagation();
          showWord(token);
        }
      });
      original.append(span);
    });
    if (!line.text) original.textContent = "· · ·";
    row.append(original);
    if (line.translation) {
      const translated = document.createElement("div");
      translated.className = "lyric-translation";
      translated.textContent = line.translation;
      if (line.machineTranslation) {
        const label = document.createElement("span");
        label.className = "machine-label";
        label.textContent = "机译";
        translated.append(label);
      }
      row.append(translated);
    }
    const jump = () => {
      if (line.start !== null) seek(line.start + state.offset, true);
      else toast("纯文本歌词没有时间标签。");
    };
    row.addEventListener("click", jump);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        jump();
      }
    });
    fragment.append(row);
  });
  $("lyrics").replaceChildren(fragment);
  lyricRows = Array.from($("lyrics").children);
  activeTokens = [];
  $("empty").hidden = !!state.lines.length;
  lastRenderActive = -2;
  state.resumeFollowAt = 0;
  $("followButton").hidden = true;
}
function rubyParts(token) {
  if (token.language !== "ja" || !token.reading) return [token];
  const hira = text => text.replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 96));
  const pieces = token.text.match(/[\u3400-\u9fff々]+|[^\u3400-\u9fff々]+/g) || [];
  const reading = hira(token.reading), solutions = [];
  function split(index, cursor, parts) {
    if (solutions.length > 1) return;
    if (index === pieces.length) {
      if (cursor === reading.length) solutions.push(parts);
      return;
    }
    const text = pieces[index];
    if (!/[\u3400-\u9fff々]/.test(text)) {
      if (reading.startsWith(hira(text), cursor)) split(index + 1, cursor + text.length, [...parts, {text, reading:""}]);
      return;
    }
    for (let end = cursor + 1; end <= reading.length; end++) {
      split(index + 1, end, [...parts, {text, reading: reading.slice(cursor, end)}]);
      if (solutions.length > 1) return;
    }
  }
  split(0, 0, []);
  // 内部假名也作为锚点：逃(に)げ出(だ)し。熟字训或边界歧义保留整词。
  return solutions.length === 1 ? solutions[0] : [token];
}
function updateHighlight(position) {
  const lyricPosition = position - state.offset,
    index = currentIndex(lyricPosition);
  state.active = index;
  if (index !== lastRenderActive) {
    // 只有换行时更新行状态；每帧只更新当前行的字词，长歌词不会逐帧遍历 DOM。
    lyricRows.forEach((r, i) => {
      r.classList.toggle("past", index >= 0 && i < index);
      r.classList.toggle("active", i === index);
      if (i !== index) r.removeAttribute("aria-current");
    });
    const row = lyricRows[index];
    row?.classList.add("active");
    row?.setAttribute("aria-current", "true");
    activeTokens = row ? Array.from(row.querySelectorAll(".token-base")) : [];
    followCurrent();
    lastRenderActive = index;
    $("lyricCounter").textContent =
      `${index < 0 ? "—" : String(index + 1).padStart(2, "0")} / ${String(state.lines.length).padStart(2, "0")}`;
  }
  if (index < 0) return;
  const line = state.lines[index],
    end = lineEnd(index);
  const clamp = value => Math.max(0, Math.min(1, value));
  const characters = end > line.start ? clamp((lyricPosition - line.start) / (end - line.start)) * line.text.length : 0;
  let wordCursor = 0;
  const timedWords = line.timing === "word" ? line.words.map(word => {
    const start = wordCursor;
    wordCursor += word.text.length;
    return {start, end: wordCursor, progress: clamp((lyricPosition - word.start) / Math.max(1, (word.end ?? end) - word.start))};
  }) : [];
  for (const token of activeTokens) {
    const start = Number(token.dataset.start),
      end = Number(token.dataset.end);
    // 按原始字词范围着色，重叠时间或停顿不会把下一词的进度挤到前一词。
    const passed = timedWords.length ? timedWords.reduce((sum, word) => {
      const sungEnd = word.start + (word.end - word.start) * word.progress;
      return sum + Math.max(0, Math.min(end, word.end, sungEnd) - Math.max(start, word.start));
    }, 0) : characters - start;
    token.style.setProperty(
      "--fill",
      `${clamp(passed / Math.max(1, end - start)) * 100}%`,
    );
  }
}
// 居中模式给首尾留半屏空白；坐标以 viewport 为基准，避免 offsetParent 不同造成偏移。
function followCurrent() {
  if (!state.follow || state.resumeFollowAt > performance.now()) return;
  const row = lyricRows[state.active], viewport = $("lyricViewport");
  if (!row) return;
  const rect = row.getBoundingClientRect(), outer = viewport.getBoundingClientRect();
  let target = viewport.scrollTop;
  if (state.followMode === "center") target += rect.top - outer.top - (viewport.clientHeight - rect.height) / 2;
  else if (rect.bottom > outer.bottom - 35 || rect.top < outer.top) target += rect.top - outer.top - 35;
  state.scrollTarget = Math.max(0, Math.min(viewport.scrollHeight - viewport.clientHeight, target));
}
function frame(now) {
  const elapsed = Math.min(50, now - (previousFrame || now));
  previousFrame = now;
  if (state.follow && state.resumeFollowAt && now >= state.resumeFollowAt) {
    state.resumeFollowAt = 0;
    $("followButton").hidden = true;
    followCurrent();
  }
  if (state.scrollTarget !== null) {
    const viewport = $("lyricViewport"), delta = state.scrollTarget - viewport.scrollTop;
    // 根据经过的毫秒计算动画速度，170 Hz 与 60 Hz 上拥有相同的过渡时长。
    // Chromium 将 scrollTop 量化为设备像素；末段至少移动一像素，避免渐近插值卡住。
    const pixel = 1 / devicePixelRatio;
    const step = Math.sign(delta) * Math.min(Math.abs(delta), Math.max(pixel, Math.abs(delta) * (1 - Math.exp(-elapsed / 65))));
    viewport.scrollTop += matchMedia("(prefers-reduced-motion: reduce)").matches ? delta : step;
    if (Math.abs(delta) <= pixel) { viewport.scrollTop = state.scrollTarget; state.scrollTarget = null; }
  }
  const position = state.dragging
    ? Number($("seek").value)
    : estimatedPosition();
  if (!state.dragging) $("seek").value = position;
  $("position").textContent = state.hasTimeline ? time(position) : "— — : — —";
  $("seek").style.setProperty(
    "--progress",
    `${state.duration ? (position / state.duration) * 100 : 0}%`,
  );
  if (state.hasTimeline) updateHighlight(position);
  // 暂停且无滚动动画时降低唤醒频率；播放期间完整使用引擎的 rAF 节拍。
  if (state.playing || state.dragging || state.scrollTarget !== null) requestAnimationFrame(frame);
  else setTimeout(() => requestAnimationFrame(frame), 80);
}
function loopLine() {
  if (state.loop) {
    action("loop", null);
    return;
  }
  const index = state.active;
  if (index < 0 || !state.lines[index] || state.lines[index].start === null) {
    toast("请先选择或播放一句带时间的歌词。");
    return;
  }
  action("loop", [
    Math.max(0, state.lines[index].start + state.offset),
    Math.min(state.duration, lineEnd(index) + state.offset),
  ]);
}
function showSearch(data) {
  $("toast").hidden = true;
  $("searchHint").textContent = data.automatic
    ? "发现多个可能的版本，请选择与当前音频一致的歌曲。"
    : "点击一项，将它的歌词加载到当前音频。";
  $("searchResults").replaceChildren();
  if (!data.songs.length)
    $("searchResults").textContent =
      "未找到歌曲，请尝试更短的歌名或输入歌曲 ID。";
  for (const song of data.songs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result";
    const title = document.createElement("strong"),
      artist = document.createElement("span");
    title.textContent = song.title;
    artist.textContent = `${song.artist} · ${time(song.duration).slice(0, -4)} · ID ${song.id}`;
    button.append(title, artist);
    button.onclick = () => {
      action("selectSong", song);
      $("searchDialog").close();
    };
    $("searchResults").append(button);
  }
  if (!$("searchDialog").open) $("searchDialog").showModal();
}
let pendingUpdate = null;
function showPendingUpdate() {
  // 启动更新结果可能先于路径引导完成；等已有弹窗关闭后再提示，避免叠加焦点。
  if (!pendingUpdate || document.querySelector("dialog[open]")) return;
  const data = pendingUpdate;
  pendingUpdate = null;
  $("updateDescription").textContent = `当前版本 ${data.current}，最新正式版本 ${data.version}。是否前往下载更新？`;
  $("updateDialog").showModal();
}
document.querySelectorAll("dialog").forEach(dialog => {
  dialog.addEventListener("close", () => setTimeout(showPendingUpdate, 0));
});
function onEvent(kind, data) {
  if (kind === "mode") setMode(data.mode);
  else if (kind === "appVersion") {
    $("appVersion").textContent = `v${data.version}`;
    $("sidebarVersion").textContent = `咏伴 ${data.version} · 让语言在歌声里熟悉`;
  } else if (kind === "updateStatus") {
    $("checkUpdate").disabled = !!data.busy;
    $("checkUpdate").textContent = data.busy ? "检查中…" : "检查更新";
    if (data.busy) $("updateFeedback").textContent = "正在检查 GitHub 正式版本…";
    else $("updateFeedback").textContent = "检查已完成。每次启动会自动检查正式版本。";
  } else if (kind === "updateResult") {
    if (data.status === "available") {
      $("updateFeedback").textContent = `发现新版本 ${data.version}（当前 ${data.current}）。`;
      pendingUpdate = data;
      // 手动检查从设置发起时直接转入更新提示；其他弹窗仍等待正常关闭。
      if (data.manual && $("toolsDialog").open) $("toolsDialog").close();
      showPendingUpdate();
    } else {
      const message = data.status === "current" ? `当前版本 ${data.current} 无需更新（GitHub 正式版本：${data.version}）。` : data.message;
      $("updateFeedback").textContent = message;
      if (!$("toolsDialog").open) toast(message, data.status === "error");
    }
  }
  else if (kind === "clientSettings") {
    clientDirectory = data.directory || "";
    $("clientDirectorySummary").textContent = clientDirectory || "尚未设置";
    if (data.saved) $("clientPathDialog").close();
    if (data.setup) openClientPath(true);
  } else if (kind === "clientPathSelected") {
    $("clientPathInput").value = data.directory;
    $("clientPathError").hidden = true;
    $("clientPathInput").removeAttribute("aria-invalid");
  } else if (kind === "clientPathError") {
    $("clientPathError").textContent = data.message;
    $("clientPathError").hidden = false;
    $("clientPathInput").setAttribute("aria-invalid", "true");
    $("clientPathInput").focus();
  } else if (kind === "clientStatus") {
    $("connectCloud").disabled = !!data.busy;
    $("connectCloud").textContent = data.busy ? "连接中…" : "连接客户端";
    for (const id of ["editClientPath", "browseClientPath", "saveClientPath"]) $(id).disabled = !!data.busy;
    if (!data.busy) $("toast").hidden = true;
  } else if (kind === "clientRestartRequired") {
    // 用独立模态窗口说明副作用；Esc 和取消都只取消此次连接。
    $("clientRestartDirectory").textContent = data.directory;
    $("toast").hidden = true;
    if (!$("clientRestartDialog").open) $("clientRestartDialog").showModal();
  }
  else if (kind === "displayInfo") $("displayInfo").textContent =
    `显示器 ${data.refreshRate} Hz · ${data.unlimited ? "已解除固定帧率上限" : "系统默认刷新"}`;
  else if (kind === "track") {
    $("trackTitle").textContent = data.title;
    $("trackArtist").textContent = data.artist;
    $("searchInput").value = data.title;
    $("trackTitle").title = data.title;
    $("trackArtist").title = data.artist;
    showCover(data.cover);
  } else if (kind === "cover") {
    showCover(data.cover);
  } else if (kind === "versions") {
    const fill = (id, items, selected, fallback) => {
      const select = $(id);
      select.replaceChildren(...items.map(item => {
        const option = document.createElement("option");
        option.value = item.id; option.textContent = item.label; return option;
      }));
      if (!items.length) select.add(new Option(fallback, ""));
      select.value = selected || select.options[0]?.value || "";
      select.disabled = items.length < 2;
    };
    fill("songVersion", data.songs.map(s => ({id: String(s.id), label: `${s.title} · ${s.artist}${s.album ? ' · ' + s.album : ''}`})), String(data.songId || ""), "等待匹配");
    fill("lyricVersion", data.versions, data.selected, "等待歌词");
  } else if (kind === "lyrics") {
    state.token = null;
    $("dictEmpty").hidden = false;
    $("dictContent").hidden = true;
    $("correctDialog").close();
    state.lines = data.lines;
    $("practiceButton").disabled = !data.lines.length;
    renderLyrics();
    if (data.source) state.lyricSource = data.source;
    else if (!data.lines.length) state.lyricSource = "等待加载歌词";
    $("lyricSource").textContent = state.lyricSource;
    const timed = data.lines.some((l) => l.timing === "word");
    $("timingHint").textContent = timed
      ? "原始逐字时间 · 精细跟唱"
      : data.lines.some((l) => l.timing === "none")
        ? "无时间标签 · 自由阅读"
        : "逐行时间 · 行内着色为估算";
    const songReadings = data.lines.filter(l => l.readingSource === "song").length;
    if (data.lines.length) $("timingHint").textContent += songReadings
      ? ` · ${songReadings} 句参考歌曲读音` : " · 注音为词典推测";
    const conflicts = data.lines.flatMap(l=>l.tokens || []).filter(t=>t.readingConflict).length;
    if (conflicts) $("lyricSource").textContent += ` · ${conflicts} 处读音有分歧（虚线标记）`;
    if (data.timingIssues?.length) $("lyricSource").textContent += ` · ${data.timingIssues.length} 处时间戳疑似异常，可切换时间轴`;
    $("lyricSource").title = $("lyricSource").textContent;
  } else if (kind === "playback") updatePlayback(data);
  else if (kind === "cloud") {
    if (state.mode !== "cloud") return;
    $("connection").classList.toggle("online", data.connected);
    $("connectionLabel").textContent = data.connected
      ? (data.transport === "client" ? "客户端直连 · 双向同步" : "Windows 媒体同步")
      : "等待网易云播放";
    if (data.connected) {
      updatePlayback(data);
      $("capabilityNotice").hidden = !!data.hasTimeline;
      $("capabilityNotice").textContent =
        "Windows 接口未提供进度。点击左侧“连接客户端”，确认重启网易云后启用双向同步。";
    } else {
      updatePlayback({
        playing: false,
        position: 0,
        duration: 0,
        hasTimeline: false,
      });
      $("capabilityNotice").hidden = false;
      $("capabilityNotice").textContent =
        data.message || "请先在网易云播放一首歌。";
    }
  } else if (kind === "loop") {
    state.loop = data.enabled ? data.region || state.loop : null;
    $("lineLoop").setAttribute("aria-pressed", String(data.enabled));
    $("loopHint").textContent = data.enabled
      ? `循环 ${time(state.loop[0])} — ${time(state.loop[1])} · 点击“一句循环”退出`
      : "空格 播放 / 暂停 · ← → 微调 · 点击歌词跳转";
    if (!data.enabled) {
      state.a = null;
      $("setA").classList.remove("marked");
      $("setB").classList.remove("marked");
    }
  } else if (kind === "reset") {
    playbackClock.reset();
    state.pendingSeek = null;
    state.dragging = false;
    state.scrollTarget = null;
    state.offset = 0;
    $("offset").value = 0;
    state.active = -1;
    state.token = null;
    $("dictEmpty").hidden = false;
    $("dictContent").hidden = true;
    $("searchDialog").close();
    updatePlayback({});
  } else if (kind === "dictionary") {
    if (
      !state.token ||
      data.token.text !== state.token.text ||
      data.token.lemma !== state.token.lemma
    )
      return;
    $("dictDefinitions").replaceChildren();
    for (const definition of data.definitions) {
      const p = document.createElement("p");
      p.className = "definition";
      p.textContent = definition;
      $("dictDefinitions").append(p);
    }
    $("dictSource").textContent = data.source + " · " + state.token.source;
  } else if (kind === "search") showSearch(data);
  else if (kind === "busy") toast(data.message, false, true);
  else if (kind === "notice") toast(data.message);
  else if (kind === "error") {
    state.pendingSeek = null;
    $("practiceButton").disabled = !state.lines.length;
    toast(data.message, true);
  }
}
// 折叠状态和交互偏好沿用桌面持久 profile；缺少新字段时使用新默认值。
const foldGroups = [["displayFold", "displayGroup"], ["versionsFold", "versionsGroup"], ["infoFold", "infoGroup"]];
function setFold(button, group, collapsed) {
  $(group).hidden = collapsed;
  $(button).setAttribute("aria-expanded", String(!collapsed));
  $(button).querySelector("span").textContent = collapsed ? "▸" : "▾";
}
for (const [button, group] of foldGroups) $(button).onclick = () => {
  setFold(button, group, !$(group).hidden);
  savePreferences();
};
function savePreferences() {
  try {
    localStorage.setItem(
      "utatomo-display",
      JSON.stringify({
        ruby: $("rubyToggle").checked,
        translation: $("translationToggle").checked,
        dict: state.dict,
        size: $("fontSize").value,
        follow: state.follow,
        followMode: state.followMode,
        playOnLyricSeek: state.playOnLyricSeek,
        resumeAfterBrowse: state.resumeAfterBrowse,
        collapsed: Object.fromEntries(foldGroups.map(([button, group]) => [group, $(group).hidden])),
      }),
    );
  } catch {}
}
function display() {
  document.body.classList.toggle("hide-ruby", !$("rubyToggle").checked);
  document.body.classList.toggle(
    "hide-translation",
    !$("translationToggle").checked,
  );
  document.documentElement.style.setProperty(
    "--lyric-size",
    $("fontSize").value + "px",
  );
  $("fontSizeLabel").textContent = $("fontSize").value + " px";
  $("quickFontSize").value = $("fontSize").value;
  $("quickFontLabel").textContent = $("fontSize").value;
  followCurrent();
  savePreferences();
}
$("cloudMode").onclick = () => action("mode", "cloud");
$("localMode").onclick = () => action("mode", "local");
$("openAudio").onclick = $("emptyOpen").onclick = () => action("openAudio");
$("demoButton").onclick = () => action("demo");
$("author").onclick = () => action("author");
$("github").onclick = () => action("github");
$("checkUpdate").onclick = () => action("checkUpdate");
$("releasePage").onclick = () => action("releases");
$("laterUpdate").onclick = () => $("updateDialog").close();
$("downloadUpdate").onclick = () => {
  $("updateDialog").close();
  action("openUpdate");
};
$("connectCloud").onclick = () => action("connectCloud");
$("play").onclick = () => action("toggle");
$("previousLine").onclick = () => goLine(-1);
$("nextLine").onclick = () => goLine(1);
$("lineLoop").onclick = loopLine;
$("setA").onclick = () => {
  state.a = Math.round(estimatedPosition());
  $("setA").classList.add("marked");
  toast("循环起点 A：" + time(state.a));
};
$("setB").onclick = () => {
  if (state.a === null) {
    toast("先设置 A 点，再设置 B 点。");
    return;
  }
  const b = Math.round(estimatedPosition());
  if (b - state.a < 100) {
    toast("B 点需要在 A 点之后至少 0.1 秒。", true);
    return;
  }
  $("setB").classList.add("marked");
  action("loop", [state.a, b]);
};
$("clearLoop").onclick = () => action("loop", null);
$("speed").onchange = (e) => action("rate", Number(e.target.value));
$("nudgeBack").onclick = (e) =>
  seek(estimatedPosition() - (e.shiftKey ? 10 : 100));
$("nudgeForward").onclick = (e) =>
  seek(estimatedPosition() + (e.shiftKey ? 10 : 100));
$("seek").addEventListener("input", () => (state.dragging = true));
$("seek").addEventListener("change", () => {
  state.dragging = false;
  seek(Number($("seek").value));
});
$("seek").addEventListener("pointercancel", () => (state.dragging = false));
$("rubyToggle").onchange = $("translationToggle").onchange = display;
$("fontSize").oninput = display;
$("quickFontSize").oninput = (e) => { $("fontSize").value = e.target.value; display(); };
$("songVersion").onchange = (e) => action("selectSong", {id: e.target.value});
$("lyricVersion").onchange = (e) => action("selectVersion", e.target.value);
function changeFollow() {
  state.follow = $("autoFollow").checked;
  state.followMode = $("followMode").value;
  state.resumeFollowAt = 0;
  state.scrollTarget = null;
  $("followMode").disabled = !state.follow;
  $("lyrics").classList.toggle("center-follow", state.followMode === "center");
  $("followButton").hidden = true;
  followCurrent(); savePreferences();
}
$("autoFollow").onchange = $("followMode").onchange = changeFollow;
new ResizeObserver(() => {
  $("lyrics").style.setProperty("--viewport-height", $("lyricViewport").clientHeight + "px");
  followCurrent();
}).observe($("lyricViewport"));
$("dictionaryToggle").onchange = (e) => setDictionary(e.target.checked);
$("closeDictionary").onclick = () => setDictionary(false);
// Infinity 表示用户主动浏览，只有显式返回或跳转才恢复；程序滚动不会触发此入口。
function browseLyrics() {
  if (!state.follow) return;
  state.resumeFollowAt = state.resumeAfterBrowse ? performance.now() + 4000 : Infinity;
  state.scrollTarget = null;
  $("followButton").hidden = false;
}
$("lyricViewport").addEventListener("wheel", browseLyrics, {passive: true});
$("lyricViewport").addEventListener("touchmove", browseLyrics, {passive: true});
$("lyricViewport").addEventListener("pointerdown", e => {
  // 仅滚动条拖动暂停跟随；普通歌词点击仍执行跳转。
  if (e.target === $("lyricViewport")) browseLyrics();
});
$("lyricViewport").addEventListener("keydown", e => {
  if (["PageUp", "PageDown", "Home", "End"].includes(e.key)) browseLyrics();
});
$("followButton").onclick = () => {
  state.resumeFollowAt = 0;
  lastRenderActive = -2;
  $("followButton").hidden = true;
  followCurrent();
};
for (const key of ["playOnLyricSeek", "resumeAfterBrowse"]) $(key).onchange = () => {
  state[key] = $(key).checked;
  if (key === "resumeAfterBrowse" && state.resumeFollowAt) browseLyrics();
  savePreferences();
};
function showCover(source) {
  $("albumCover").src = source || "../assets/landscape.svg";
  $("albumCover").alt = source ? "当前歌曲封面" : "日光与山峦的原创默认封面";
  $("coverCaption").hidden = !!source;
}
$("albumCover").onerror = () => showCover("");
$("searchButton").onclick = () => $("searchDialog").showModal();
$("moreButton").onclick = () => $("toolsDialog").showModal();
let clientDirectory = "";
function openClientPath(firstRun = false) {
  $("clientPathTitle").textContent = firstRun ? "先确认网易云音乐路径" : "更改网易云音乐路径";
  $("cancelClientPath").textContent = firstRun ? "暂时跳过" : "取消";
  $("clientPathInput").value = clientDirectory;
  $("clientPathInput").removeAttribute("aria-invalid");
  $("clientPathError").hidden = true;
  if (!$("clientPathDialog").open) $("clientPathDialog").showModal();
}
$("editClientPath").onclick = () => openClientPath();
$("browseClientPath").onclick = () => action("chooseClientPath");
$("cancelClientPath").onclick = () => $("clientPathDialog").close();
$("clientPathForm").onsubmit = e => {
  e.preventDefault();
  // 后端验证存在的主程序并原子保存；成功回执到达前保留输入和弹窗。
  action("saveClientPath", $("clientPathInput").value);
};
$("confirmClientRestart").onclick = () => {
  $("clientRestartDialog").close();
  action("confirmClientRestart", true);
};
$("cancelClientRestart").onclick = () => {
  $("clientRestartDialog").close();
  action("confirmClientRestart", false);
};
$("clientRestartDialog").addEventListener("cancel", () => action("confirmClientRestart", false));
$("helpButton").onclick = () => $("helpDialog").showModal();
document
  .querySelectorAll(".close-dialog")
  .forEach((b) => (b.onclick = () => b.closest("dialog").close()));
$("searchForm").onsubmit = (e) => {
  e.preventDefault();
  $("searchResults").textContent = "正在搜索…";
  action("search", $("searchInput").value);
};
$("importLyrics").onclick = () => {
  $("toolsDialog").close();
  action("openLyrics");
};
$("importTranslation").onclick = () => {
  $("toolsDialog").close();
  action("openTranslation");
};
$("translate").onclick = () => {
  $("toolsDialog").close();
  action("translate");
};
$("offset").onchange = () => {
  state.offset = Math.max(
    -10000,
    Math.min(10000, Number($("offset").value) || 0),
  );
  action("offset", state.offset);
};
$("volume").oninput = () => {
  $("volumeLabel").textContent = $("volume").value + "%";
  action("volume", Number($("volume").value) / 100);
};
$("correctButton").onclick = () => {
  if (!state.token) return;
  $("correctWord").textContent = "词汇：" + state.token.text;
  $("correctReading").value = state.token.reading;
  $("readingCandidates").replaceChildren();
  const readings = new Set();
  for (const candidate of state.token.readingCandidates || []) {
    if (readings.has(candidate.reading)) continue;
    readings.add(candidate.reading);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${candidate.reading} · ${candidate.source}`;
    button.onclick = () => { $("correctReading").value = candidate.reading; };
    $("readingCandidates").append(button);
  }
  $("correctDialog").showModal();
};
$("correctForm").onsubmit = (e) => {
  e.preventDefault();
  action("correct", {
    text: state.token.text,
    reading: $("correctReading").value,
    scope: state.token.scope,
    lineKey: state.token.lineKey,
    tokenStart: state.token.tokenStart,
  });
  $("correctDialog").close();
};
$("dictionaryWeb").onclick = () =>
  action("dictionaryWeb", state.token?.lemma || state.token?.text || "");
// 统一在捕获阶段分派快捷键：先取消控件默认行为，再执行唯一的播放操作。
// 文本编辑、输入法组合和模态弹窗保留原生键盘交互；按钮、开关、滑块、
// 下拉框的焦点不改变快捷键含义。未绑定的键（如 Enter、Tab）仍交给控件。
function acceptsPlaybackShortcut(e) {
  const target = e.target;
  const editing = target.isContentEditable || target.closest("[contenteditable]:not([contenteditable='false'])") ||
    target.tagName === "TEXTAREA" ||
    (target.tagName === "INPUT" && !["checkbox", "radio", "range", "button", "submit", "reset"].includes(target.type));
  return !editing && !e.isComposing && !document.querySelector("dialog[open]");
}
document.addEventListener("keydown", (e) => {
  if (!acceptsPlaybackShortcut(e)) return;
  // 隐藏入口仅响应明确组合键；与普通播放快捷键及文字输入互不冲突。
  if (e.ctrlKey && e.shiftKey && !e.altKey && !e.metaKey && e.code === "KeyM") {
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!e.repeat) action("chime");
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const key = e.key.toLowerCase();
  const bound = e.code === "Space" || ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) ||
    ["l", "[", "]"].includes(key);
  if (!bound) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  // 长按方向键可连续微调；播放和循环是状态切换，长按只能触发一次。
  if (e.repeat && !e.key.startsWith("Arrow")) return;
  if (e.code === "Space") action("toggle");
  else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    seek(estimatedPosition() + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 10 : 100));
  } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
    goLine(e.key === "ArrowUp" ? -1 : 1);
  } else if (key === "l") loopLine();
  else if (key === "[") $("setA").click();
  else if (key === "]") $("setB").click();
}, true);
// 部分原生按钮在松开空格时激活，连同 keyup 一并取消，避免二次操作。
document.addEventListener("keyup", e => {
  if (e.code === "Space" && acceptsPlaybackShortcut(e) && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    e.stopImmediatePropagation();
  }
}, true);
// 双击侧栏图标也能触发，重复触发由后端从头播放，不堆积音频实例。
document.querySelector(".brand img").ondblclick = () => action("chime");

try {
  const p = JSON.parse(localStorage.getItem("utatomo-display") || "{}");
  if (p.ruby !== undefined) $("rubyToggle").checked = p.ruby;
  if (p.translation !== undefined)
    $("translationToggle").checked = p.translation;
  if (p.size) $("fontSize").value = p.size;
  if (p.follow !== undefined) $("autoFollow").checked = p.follow;
  if (["advance", "center"].includes(p.followMode)) $("followMode").value = p.followMode;
  for (const key of ["playOnLyricSeek", "resumeAfterBrowse"]) {
    if (typeof p[key] === "boolean") state[key] = p[key];
    $(key).checked = state[key];
  }
  for (const [button, group] of foldGroups) setFold(button, group, p.collapsed?.[group] === true);
  changeFollow();
  setDictionary(!!p.dict);
  display();
} catch {}
if (typeof qt !== "undefined" && typeof QWebChannel !== "undefined") {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    window.backend = channel.objects.backend;
    backend.event.connect((kind, raw) => {
      try {
        onEvent(kind, JSON.parse(raw));
      } catch (error) {
        window.__errors.push(error.message);
        console.error(error);
      }
    });
    backend.initialize();
  });
}
requestAnimationFrame(frame);

$("practiceButton").onclick = () => {
  action("practice");
};
