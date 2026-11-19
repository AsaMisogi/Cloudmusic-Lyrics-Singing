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
  romaji: false,
  cantonese: false,
  lyricFont: "",
  correctionToken: null,
  token: null,
  loop: null,
  a: null,
  offset: 0,
};
window.__errors = [];
window.addEventListener("error", (e) => window.__errors.push(e.message));
let toastTimer,
  lastRenderActive = -2;
const reducedMotion=matchMedia("(prefers-reduced-motion: reduce)");
let frameTicket=0, wakeTimer=0, refreshHz=60, nextPaint=0, unlockedFrames=false;
let controlSignature="";
let lyricRows = [], activeTokens = [], previousFrame = 0;
let modalOpen = false, lastPlayback = {}, lastCloud = null;
const setText = (element, value) => { if (element.textContent !== String(value)) element.textContent = value; };
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
  lastPlayback = data;
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
  // 弹窗不需要重绘背后的毫秒计时、按钮与进度条；真实播放状态继续接收。
  if (!modalOpen) {renderPlaybackControls();scheduleFrame();}
}
function renderPlaybackControls() {
  const data = lastPlayback;
  const signature=[state.playing,state.duration,state.canSeek,state.canRate,state.rate,data.canPlay].join("|");
  if(signature===controlSignature)return;
  controlSignature=signature;
  setText($("playGlyph"), state.playing ? "Ⅱ" : "▶");
  $("play").setAttribute("aria-label", state.playing ? "暂停" : "播放");
  $("seek").disabled = !state.canSeek;
  $("seek").max = Math.max(1, state.duration);
  $("play").disabled = data.canPlay === false;
  setText($("duration"), time(state.duration));
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
  if (mode !== state.mode && $("playerVolumePanel").matches(":popover-open")) $("playerVolumePanel").hidePopover();
  state.mode = mode;
  lastCloud = null;
  updateConnectLabel();
  $("practiceButton").hidden = mode !== "cloud";
  $("connectCloud").hidden = mode !== "cloud";
  $("cloudMode").setAttribute("aria-pressed", String(mode === "cloud"));
  $("localMode").setAttribute("aria-pressed", String(mode === "local"));
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
    (state.romaji && token.language === "ja" ? token.romaji : "") || token.reading || (token.language === "ja" ? token.text : "暂无词典音标");
  $("dictPos").textContent = token.pos || "词汇";
  $("correctButton").textContent = token.language === "zh" ? "修正粤拼" : "修正注音";
  $("dictionaryWeb").hidden = token.language === "zh";
  $("dictDefinitions").textContent = "正在查询中文释义…";
  $("dictSource").textContent = token.source;
  action("dictionary", token);
}
function displayTokens(line) {
  if (!line.cantoneseTokens) return line.tokens || [{text: line.text, reading: ""}];
  // 中文关闭粤拼时保留英文 IPA，不把同形汉字显示成日语词典猜读。
  return state.cantonese ? line.cantoneseTokens : line.cantoneseTokens.map(token =>
    token.language === "zh" ? {...token, reading: "", readingCandidates: []} : token);
}
function appendLineTokens(original, line) {
  let character = 0;
  // 后端断点按 Unicode 码点计数，DOM 的文本切片使用 UTF-16。
  const cuts=(line.breaks||[]).map(i=>Array.from(line.text).slice(0,i).join('').length);
  for (const token of displayTokens(line)) {
    const span = document.createElement("span");
    span.className = "token" + (token.language === "en" ? " en" : token.language === "zh" ? " zh" : "");
    span.dataset.start = character;
    character += token.text.length;
    span.dataset.end = character;
    span.dataset.clickable = !!token.language && !!token.text.trim();
    span.classList.toggle("reading-conflict", !!token.readingConflict);
    if (token.reading) span.title = `${token.reading} · ${token.source || "自动注音"}` +
      (token.readingConflict ? "\n读音有分歧，词典模式中可比较并修正：" +
        token.readingCandidates.map(c=>`${c.reading}（${c.source}）`).join(" / ") : "");
    span.breaks=cuts;
    span.lyricToken = token;
    renderTokenReading(span, token);
    span.addEventListener("click", (e) => {
      const current = span.lyricToken;
      if (state.dict && !e.shiftKey && current.language) {
        e.stopPropagation();
        // 保留查词位置的视觉反馈；只更新两枚词节点，不重排本句、不干扰逐字进度。
        document.querySelector(".token.looked-up")?.classList.remove("looked-up");
        span.classList.add("looked-up");
        showWord(current);
      }
    });
    original.append(span);
  }
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
    appendLineTokens(original, line);
    if (!line.text) original.textContent = "· · ·";
    row.append(original);
    drawSegments(row,line);
    const edit=document.createElement("button");
    edit.type="button";edit.className="edit-line";edit.textContent="分段";edit.setAttribute("aria-label","编辑本句原文与分段");
    edit.onclick=event=>{event.stopPropagation();action("editSegments",index);};
    row.append(edit);
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
      else { action("desktopLine",index); toast("已选中这一句 · 纯文本无时间轴"); }
    };
    row.addEventListener("click", jump);
    row.addEventListener("keydown", (e) => {
      if (e.target===row && e.key === "Enter") {
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
function refreshCantonese() {
  state.cantonese = $("cantoneseToggle").checked;
  state.lines.forEach((line, index) => {
    if (!line.cantoneseTokens) return;
    const original = lyricRows[index]?.querySelector(".lyric-original");
    if (original) { original.replaceChildren(); appendLineTokens(original, line); }
  });
  state.token = null;
  $("dictEmpty").hidden = false; $("dictContent").hidden = true;
  activeTokens = Array.from(lyricRows[state.active]?.querySelectorAll(".token-base") || []);
  updateHighlight(estimatedPosition()); followCurrent(); savePreferences();
}
function patchReadings(data) {
  // 修正只更新有变化的词，保留行对象、滚动位置、循环及手动浏览状态。
  if (data.lines.length !== state.lines.length || data.lines.some((line, i) =>
    line.text !== state.lines[i].text || line.start !== state.lines[i].start)) return;
  state.lines = data.lines;
  data.lines.forEach((line, i) => {
    const tokens = displayTokens(line);
    lyricRows[i]?.querySelectorAll(".token").forEach((span, index) => {
      const token = tokens[index];
      if (!token) return;
      if (token.reading !== span.lyricToken.reading || token.romaji !== span.lyricToken.romaji) {
        span.lyricToken = token; renderTokenReading(span, token);
        span.title = token.reading ? `${token.reading} · ${token.source}` : "";
      } else span.lyricToken = token;
    });
  });
  const saved = data.token;
  state.token = data.lines.flatMap(line => displayTokens(line)).find(token => token.scope === saved.scope &&
    token.lineKey === saved.lineKey && token.tokenStart === saved.tokenStart && token.text === saved.text &&
    (token.readingSystem || "default") === (saved.readingSystem || "default")) || null;
  if (state.token) showWord(state.token);
  activeTokens = Array.from(lyricRows[state.active]?.querySelectorAll(".token-base") || []);
  $("correctDialog").close();
  $("saveReading").disabled = false; $("saveReading").textContent = "保存注音";
  toast("注音已保存。");
}
function renderTokenReading(span, token) {
  // 罗马音按整个词的最终读音展示：不在假名锚点处拆开促音、拗音等组合。
  // 默认模式仍沿用原有汉字分段 ruby；英语继续展示原来的 IPA。
  const romanized = state.romaji && token.language === "ja" && !!token.romaji;
  const parts = romanized ? [{text: token.text, reading: token.romaji}] : (token.rubyParts || [token]);
  span.classList.toggle("has-reading", !!token.reading || romanized);
  span.replaceChildren();
  let partStart = Number(span.dataset.start);
  for (const part of parts) {
    const begin = partStart;
    partStart += part.text.length;
    const body = part.reading ? document.createElement("ruby") : span;
    let pos = begin;
    function appendBase(end) {
      if (end === pos) return;
      const base = document.createElement("span");
      base.className = "token-base";
      base.dataset.start = pos;
      base.dataset.end = end;
      base.textContent = part.text.slice(pos - begin, end - begin);
      body.append(base);
      pos = end;
    }
    // 每个唱词片段单独着色。斜线和留白没有时间，也不把注音或查词目标切成两个词。
    for (const cut of span.breaks || []) {
      if (cut < begin || cut >= partStart) continue;
      appendBase(cut);
      const mark = document.createElement("i");
      mark.className = "breath";
      mark.setAttribute("aria-hidden","true");
      (cut === begin ? span : body).append(mark);
    }
    appendBase(partStart);
    if (part.reading) {
      const rt = document.createElement("rt");
      rt.textContent = part.reading;
      body.append(rt);
      span.append(body);
    }
  }
}
function changeRomaji() {
  state.romaji = $("romajiToggle").checked;
  lyricRows.forEach((row,i)=>drawSegments(row,state.lines[i]));
  // 不调用 renderLyrics，保留当前焦点、手动浏览暂停、循环和歌词行对象。
  document.querySelectorAll(".lyric-original .token").forEach(span => {
    if (span.lyricToken.language === "ja") renderTokenReading(span, span.lyricToken);
  });
  if (state.token?.language === "ja") $("dictReading").textContent =
    (state.romaji ? state.token.romaji : "") || state.token.reading || state.token.text;
  const row = lyricRows[state.active];
  activeTokens = row ? Array.from(row.querySelectorAll(".token-base")) : [];
  updateHighlight(estimatedPosition());
  followCurrent();
  savePreferences();
}
const wordBoundaries=new WeakMap();
function updateHighlight(position) {
  const lyricPosition = position - state.offset,
    index = currentIndex(lyricPosition);
  state.active = index;
  if (index !== lastRenderActive) {
    // 只有换行时更新行状态；每帧只更新当前行的字词，长歌词不会逐帧遍历 DOM。
    // 正常逐句播放只更新上一句和当前句；跳转才触及跨过的行。
    const first=lastRenderActive < -1 ? 0 : Math.max(0,Math.min(index,lastRenderActive));
    const stop=lastRenderActive < -1 ? lyricRows.length : Math.max(index,lastRenderActive)+1;
    for(let i=first;i<stop;i++){
      const r=lyricRows[i];
      r.classList.toggle("past", index>=0 && i<index);
      r.classList.toggle("active",i===index);
      if(i!==index)r.removeAttribute("aria-current");
    }
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
  // 时间段的原文边界只解析一次。双游标只访问与当前字组相交的词；
  // 词间停顿和时间重叠按各自原始时间计算，不用全句平均速度取代。
  let intervals=[];
  if(line.timing==="word" && line.words){
    if(!wordBoundaries.has(line.words)){
      let offset=0;
      wordBoundaries.set(line.words,line.words.map(w=>{
        const start=offset; offset+=w.text.length;
        return {start,stop:offset,word:w};
      }));
    }
    intervals=wordBoundaries.get(line.words);
  }
  let j=0;
  for(const token of activeTokens){
    const start=Number(token.dataset.start),stop=Number(token.dataset.end);
    let passed=characters-start;
    if(intervals.length){
      while(j<intervals.length && intervals[j].stop<=start)++j;
      passed=0;
      for(let k=j;k<intervals.length && intervals[k].start<stop;k++){
        const w=intervals[k], frac=clamp((lyricPosition-w.word.start)/Math.max(1,(w.word.end??end)-w.word.start));
        passed+=Math.max(0,Math.min(stop,w.start+(w.stop-w.start)*frac)-Math.max(start,w.start));
      }
    }
    const value=clamp(passed/Math.max(1,stop-start))*100;
    if(value!==token.lastFill){token.lastFill=value;token.style.setProperty("--fill",value+"%");}
  }
}
// 居中模式给首尾留半屏空白；坐标以 viewport 为基准，避免 offsetParent 不同造成偏移。
function followCurrent() {
  if (modalOpen) return;
  if (!state.follow || pointerOnScrollbar || state.resumeFollowAt > performance.now()) return;
  const row = lyricRows[state.active], viewport = $("lyricViewport");
  if (!row) return;
  const rect = row.getBoundingClientRect(), outer = viewport.getBoundingClientRect();
  let target = viewport.scrollTop;
  if (state.followMode === "center") target += rect.top - outer.top - (viewport.clientHeight - rect.height) / 2;
  else if (rect.bottom > outer.bottom - 35 || rect.top < outer.top) target += rect.top - outer.top - 35;
  state.scrollTarget = Math.max(0, Math.min(viewport.scrollHeight - viewport.clientHeight, target));
  scheduleFrame();
}
// 同一显示帧只排队一次；原生滚轮、播放快照和交互都可以直接唤醒，无需等暂停轮询。
function scheduleFrame(){
  if(frameTicket || modalOpen || document.hidden) return;
  const request=()=>{frameTicket=requestAnimationFrame(frame);};
  const ahead=nextPaint-performance.now();
  // 解限模式下，Chromium 在没有新画面时会将下一次 rAF 延至空闲帧。
  // 连续动画按屏幕截止时刻直接提交一帧，避免“先等定时器、再等空闲 rAF”双重节流。
  // 标准模式保持原生 rAF；停止动画或页面隐藏时都不保留持续定时器。
  if(unlockedFrames && ahead>1 && (state.playing || state.scrollTarget!==null))
    frameTicket=-setTimeout(()=>frame(performance.now()),ahead);
  else request();
}
document.addEventListener("visibilitychange",()=>{if(!document.hidden)scheduleFrame();});
function frame(now) {
  frameTicket=0;
  // 部分 Qt 后端在持续绘制时给出远多于屏幕刷新率的 rAF。按实际屏幕限绘，
  // 用绝对截止时刻保留小数毫秒，不把 144 Hz 拆成一连串固定 16 ms 的步长。
  now=performance.now();
  if(now+.6<nextPaint){scheduleFrame();return;}
  const period=1000/refreshHz;
  nextPaint=(now-nextPaint>period ? now : nextPaint)+period;
  const elapsed = Math.min(50, now - (previousFrame || now));
  previousFrame = now;
  if (modalOpen || document.hidden) {
    // 降低合成唤醒，避免部分显卡上弹窗与歌词渐变反复争用重绘层。

    return;
  }
  if (state.follow && !pointerOnScrollbar && state.resumeFollowAt && now >= state.resumeFollowAt) {
    state.resumeFollowAt = 0;
    $("followButton").hidden = true;
    followCurrent();
  }
  const target = state.scrollTarget;
  if (target !== null) {
    const viewport = $("lyricViewport"), delta = target - viewport.scrollTop;
    // 根据经过的毫秒计算动画速度，170 Hz 与 60 Hz 上拥有相同的过渡时长。
    // Chromium 将 scrollTop 量化为设备像素；末段至少移动一像素，避免渐近插值卡住。
    const pixel = 1 / devicePixelRatio;
    const step = Math.sign(delta) * Math.min(Math.abs(delta), Math.max(pixel, Math.abs(delta) * (1 - Math.exp(-elapsed / 65))));
    viewport.scrollTop += reducedMotion.matches ? delta : step;
    if (Math.abs(delta) <= pixel || reducedMotion.matches) { viewport.scrollTop = target; state.scrollTarget = null; }
  }
  const position = state.dragging
    ? Number($("seek").value)
    : estimatedPosition();
  if (!state.dragging) $("seek").value = position;
  setText($("position"), state.hasTimeline ? time(position) : "— — : — —");
  $("seek").style.setProperty(
    "--progress",
    `${state.duration ? (position / state.duration) * 100 : 0}%`,
  );
  if (state.hasTimeline) updateHighlight(position);
  // 暂停且无滚动动画时降低唤醒频率；播放期间完整使用引擎的 rAF 节拍。
  if (state.playing || state.dragging || state.scrollTarget !== null) scheduleFrame();
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
// 原生 dialog 的 open 属性是唯一模态依据，嵌套弹窗或 Esc 均使用同一路径。
new MutationObserver(() => {
  const open = !!document.querySelector("dialog[open]");
  if (open === modalOpen) return;
  modalOpen = open;
  if (!open) {
    scheduleFrame();renderPlaybackControls();
    if (lastCloud && state.mode === "cloud") renderCloudStatus(lastCloud);
    updateHighlight(estimatedPosition()); followCurrent();
  }
}).observe(document.body, {subtree: true, attributes: true, attributeFilter: ["open"]});
function onEvent(kind, data) {
  if (typeof practiceEvent === "function" && practiceEvent(kind,data)) return;
  if (kind === "playerVolume") {
    if(data.mode!==state.mode || data.request!==mixerRequest) return;
    const ready=Number.isInteger(data.percent);
    $("mixerSlider").disabled=!ready;
    $("mixerLevel").textContent=ready?data.percent+"%":"—";
    if(ready){
      $("mixerSlider").value=data.percent;
      $("mixerSlider").style.setProperty("--progress",data.percent+"%");
      if(data.mode==="local"){
        $("volume").value=data.percent;
        $("volumeLabel").textContent=data.percent+"%";
      }
    }
    mixerTarget=data.target||null;
    $("mixerHint").textContent=data.message||(state.mode==="local"?"本地播放器":"Windows 混音器 · 仅网易云音乐");
  } else if (kind === "lyricFonts") setLyricFonts(data.families || []);
  else if (kind.startsWith("library") || kind === "playlistCreated") {
    if (typeof libraryEvents === "function") libraryEvents(kind, data);
  } else if (kind === "readingCorrected") patchReadings(data);
  else if (kind === "correctError") {
    $("correctError").textContent = data.message; $("correctError").hidden = false;
    $("saveReading").disabled = false; $("saveReading").textContent = "保存注音";
  } else if (kind === "mode") setMode(data.mode);
  else if (kind === "appVersion") {
    $("appVersion").textContent = `v${data.version}`;
    $("sidebarVersion").textContent = `Utatomo ${data.version}`;
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
    $("connectCloud").setAttribute("aria-busy", String(!!data.busy));
    updateConnectLabel();
    for (const id of ["editClientPath", "browseClientPath", "saveClientPath"]) $(id).disabled = !!data.busy;
    if (!data.busy) $("toast").hidden = true;
  } else if (kind === "clientRestartRequired") {
    // 用独立模态窗口说明副作用；Esc 和取消都只取消此次连接。
    $("clientRestartDirectory").textContent = data.directory;
    $("toast").hidden = true;
    if (!$("clientRestartDialog").open) $("clientRestartDialog").showModal();
  }
  else if (kind === "displayInfo") {
    refreshHz=data.refreshRate>0?data.refreshRate:60; unlockedFrames=!!data.unlimited; nextPaint=0;
    $("displayInfo").textContent="当前屏幕 "+refreshHz+" Hz · 动画随屏幕刷新率调度";
  }
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
    $("timingHint").textContent = !data.lines.length ? "等待时间轴" : timed
      ? "原始逐字时间 · 精细跟唱"
      : data.lines.some((l) => l.timing === "none")
        ? "无时间标签 · 自由阅读"
        : "逐行时间 · 行内着色为估算";
    const songReadings = data.lines.filter(l => l.readingSource === "song").length;
    if (data.lines.length) $("timingHint").textContent += songReadings
      ? ` · ${songReadings} 句参考歌曲读音` : data.lines.some(l=>l.inlineReadings?.length) ? " · 含原文指定注音" : " · 注音为词典推测";
    const conflicts = data.lines.flatMap(l=>l.tokens || []).filter(t=>t.readingConflict).length;
    if (conflicts) $("lyricSource").textContent += ` · ${conflicts} 处读音有分歧（虚线标记）`;
    if (data.timingIssues?.length) $("lyricSource").textContent += ` · ${data.timingIssues.length} 处时间戳疑似异常，可切换时间轴`;
    $("lyricSource").title = $("lyricSource").textContent;
  } else if (kind === "playback") updatePlayback(data);
  else if (kind === "cloud") {
    $("libraryConnectCloud").hidden = data.transport === "client";
    if (state.mode !== "cloud") return;
    lastCloud = data;
    if (data.connected) updatePlayback(data);
    else updatePlayback({playing: false, canPlay:false, position: 0, duration: 0, hasTimeline: false});
    if (!modalOpen) renderCloudStatus(data);
  } else if (kind === "loop") {
    state.loop = data.enabled ? data.region || state.loop : null;
    $("lineLoop").setAttribute("aria-pressed", String(data.enabled));
    $("clearLoop").disabled = !data.enabled;
    $("loopHint").hidden = !data.enabled;
    $("loopHint").textContent = data.enabled
      ? `循环 ${time(state.loop[0])} — ${time(state.loop[1])}`
      : "";
    if (!data.enabled) {
      state.a = null;
      $("setA").title="设置循环起点（[）"; $("setB").title="设置终点并循环所选区间（]）";
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
    if (!state.token || data.token.text !== state.token.text || data.token.lemma !== state.token.lemma ||
      data.token.scope !== state.token.scope || data.token.lineKey !== state.token.lineKey ||
      data.token.tokenStart !== state.token.tokenStart) return;
    $("dictDefinitions").replaceChildren();
    for (const definition of data.definitions) {
      const p = document.createElement("p"); p.className = "definition"; p.textContent = definition;
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
// 区分「正在连接」「可以连接」「已连接」；忙状态来自操作回执，不能被随后到达的播放快照覆盖。
function updateConnectLabel() {
  const direct = state.mode === "cloud" && lastCloud?.connected && lastCloud.transport === "client";
  setText($("connectLabel"), $("connectCloud").disabled ? "连接中…" : direct ? "查看连接" : "连接客户端");
}
function renderCloudStatus(data) {
    updateConnectLabel();
    $("connection").classList.toggle("online", data.connected);
    setText($("connectionLabel"), data.connected
      ? (data.transport === "client" ? "客户端直连 · 双向同步" : "Windows 媒体同步")
      : "等待网易云播放");
    if (data.connected) {
      $("capabilityNotice").hidden = !!data.hasTimeline;
      setText($("capabilityNotice"), "Windows 接口未提供进度。点击左栏“连接客户端”，确认重启网易云后启用双向同步。");
    } else {
      $("capabilityNotice").hidden = false;
      setText($("capabilityNotice"), data.message || "请先在网易云播放一首歌。");
    }
}
// 只读取旧配置中仍有意义的版本栏字段。旧版曾折叠「显示」，升级后也要看得到注音与词典。
function setVersionsCollapsed(collapsed) {
  $("versionsGroup").hidden = collapsed;
  $("versionsFold").setAttribute("aria-expanded", String(!collapsed));
}
$("versionsFold").onclick = () => {
  setVersionsCollapsed(!$("versionsGroup").hidden);
  savePreferences();
};
// 空格是全局播放键；五个勾选项另外支持 Tab 聚焦、Enter 开关，不与播放快捷键冲突。
document.querySelector(".display-switches").addEventListener("keydown", e => {
  if (e.target.matches("input") && e.key === "Enter" && !e.repeat) {
    e.preventDefault();
    e.target.click();
  }
});
function savePreferences() {
  try {
    localStorage.setItem(
      "utatomo-display",
      JSON.stringify({
        theme: Theme.snapshot(),
        ruby: $("rubyToggle").checked,
        translation: $("translationToggle").checked,
        dict: state.dict,
        romaji: state.romaji,
        cantonese: state.cantonese,
        size: $("fontSize").value,
        lyricFont: state.lyricFont,
        follow: state.follow,
        followMode: state.followMode,
        playOnLyricSeek: state.playOnLyricSeek,
        resumeAfterBrowse: state.resumeAfterBrowse,
        collapsed: {versionsGroup: $("versionsGroup").hidden},
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
// 只改 CSS 字体变量，不重建歌词行；逐字时间、注音、循环与浏览状态均保留。
const defaultLyricFont = '"Microsoft YaHei", "Yu Gothic", "Segoe UI", sans-serif';
function applyLyricFont() {
  const family = state.lyricFont ? JSON.stringify(state.lyricFont) + ", " + defaultLyricFont : defaultLyricFont;
  document.documentElement.style.setProperty("--lyric-font", family);
}
function setLyricFonts(families) {
  const fonts = [...new Set(families.filter(name => typeof name === "string" && name && !name.startsWith("@")))];
  fonts.sort((a,b) => a.localeCompare(b, "zh-CN"));
  const select = $("lyricFont");
  select.replaceChildren(new Option("默认 · 统一黑体", ""), ...fonts.map(name => new Option(name, name)));
  const missing = state.lyricFont && !fonts.includes(state.lyricFont);
  $("lyricFontHint").textContent = missing ? `本机未安装「${state.lyricFont}」，已使用默认字体。可重新选择。` : "使用本机已安装的字体；原文即时预览，注音保持清晰易读的字体。";
  if (missing) state.lyricFont = "";
  select.value = state.lyricFont; applyLyricFont(); savePreferences();
}
$("lyricFont").onchange = () => {
  state.lyricFont = $("lyricFont").value;
  $("lyricFontHint").textContent = "字体已保存，歌词原文即时生效。缺少的字形由系统回退字体补全。";
  applyLyricFont(); savePreferences();
};
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
$("connectCloud").onclick = () => {
  // 已直连时原操作仅报告状态；直接打开详情，不暗示会重启或重连。
  if (lastCloud?.connected && lastCloud.transport === "client") $("sessionStatus").showPopover();
  else action("connectCloud");
};
$("play").onclick = () => action("toggle");
$("previousLine").onclick = () => goLine(-1);
$("nextLine").onclick = () => goLine(1);
$("lineLoop").onclick = loopLine;
$("setA").onclick = () => {
  state.a = Math.round(estimatedPosition());
  $("setA").classList.add("marked");
  $("setA").title="循环起点："+time(state.a);
  $("setB").title="在当前位置结束并循环（起点 "+time(state.a)+"）";
  $("clearLoop").disabled = false;
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
$("seek").addEventListener("input", () => {state.dragging=true;scheduleFrame();});
$("seek").addEventListener("change", () => {
  state.dragging = false;
  seek(Number($("seek").value));
});
$("seek").addEventListener("pointercancel", () => (state.dragging = false));
$("rubyToggle").onchange = $("translationToggle").onchange = display;
$("romajiToggle").onchange = changeRomaji;
$("cantoneseToggle").onchange = refreshCantonese;
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
// 浏览不需要重画播放器。只挂一个闹钟；滚动惯性期间更新截止时间，闹钟到点再核对。
// 只有真正需要恢复跟随才唤醒动画帧；默认手动返回时连这一个定时器也不需要。
function wakeFollow() {
  wakeTimer = 0;
  if (!state.follow || !state.resumeFollowAt || !Number.isFinite(state.resumeFollowAt)) return;
  const remaining = state.resumeFollowAt - performance.now();
  if (remaining > 0) wakeTimer = setTimeout(wakeFollow, Math.ceil(remaining));
  else scheduleFrame();
}
function browseLyrics() {
  if (!state.follow) return;
  state.scrollTarget = null;
  state.resumeFollowAt = state.resumeAfterBrowse && !pointerOnScrollbar ? performance.now() + 4000 : Infinity;
  if ($("followButton").hidden) $("followButton").hidden = false;
  if (!wakeTimer && Number.isFinite(state.resumeFollowAt)) wakeFollow();
}
// 手动浏览只通知跟随状态；滚轮的距离、反向、触控板惯性和滑块拖动均由 Chromium 处理。
const lyricViewport = $("lyricViewport");
let pointerOnScrollbar=false;
lyricViewport.addEventListener("wheel", e => {
  if (!e.ctrlKey && e.deltaY) browseLyrics();
}, {passive:true});
lyricViewport.addEventListener("touchmove", browseLyrics, {passive:true});
lyricViewport.addEventListener("pointerdown", e => {
  const r = lyricViewport.getBoundingClientRect();
  if (e.target === lyricViewport && e.clientX >= r.left + lyricViewport.clientWidth) {
    pointerOnScrollbar=true; browseLyrics();
  }
});
function releaseScrollbar() {
  if (!pointerOnScrollbar) return;
  pointerOnScrollbar=false;
  browseLyrics();
}
for (const type of ["pointerup","pointercancel","blur"]) window.addEventListener(type,releaseScrollbar);
lyricViewport.addEventListener("scroll", () => {
  // 持续拖动和触控板惯性从最后一次实际位移算起；布局变化本身不算主动浏览。
  if (state.resumeAfterBrowse && state.resumeFollowAt) browseLyrics();
}, {passive:true});
lyricViewport.addEventListener("keydown", e => {
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
  $("albumCover").src = source || "../assets/sleeve.svg";
  $("albumCover").alt = source ? "当前歌曲封面" : "日光与山峦的原创默认封面";

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
// 仅打开本地图片：复用原生模态窗口的焦点管理、Esc 关闭及关窗后的歌词同步。
$("supportButton").onclick = () => $("supportDialog").showModal();
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
// 每次打开先读取真实播放器值；只在松手/键盘提交时写入会话，不在高频拖动中枚举系统设备。
let mixerRequest=0, mixerTarget=null;
function placeMixer(){
  const r=$("volumeButton").getBoundingClientRect(), panel=$("playerVolumePanel");
  panel.style.left=Math.max(8,Math.min(innerWidth-panel.offsetWidth-8,r.right-panel.offsetWidth))+"px";
  panel.style.bottom=(innerHeight-r.top+8)+"px";
}
$("playerVolumePanel").addEventListener("toggle",e=>{
  if(e.newState!=="open"){++mixerRequest;return;}
  placeMixer();mixerTarget=null;
  $("mixerTitle").textContent=state.mode==="local"?"本地音量":"网易云音量";
  $("mixerHint").textContent="正在读取音量…";$("mixerSlider").disabled=true;$("mixerLevel").textContent="—";
  action("playerVolume",{mode:state.mode,request:++mixerRequest});
});
window.addEventListener("resize",()=>{if($("playerVolumePanel").matches(":popover-open"))placeMixer();});
$("mixerSlider").oninput=e=>{
  $("mixerLevel").textContent=e.target.value+"%";
  e.target.style.setProperty("--progress",e.target.value+"%");
};
$("mixerSlider").onchange=e=>action("playerVolume",{mode:state.mode,request:++mixerRequest,target:mixerTarget,percent:Number(e.target.value)});
$("volume").oninput = () => {
  $("volumeLabel").textContent = $("volume").value + "%";
  action("volume", Number($("volume").value) / 100);
};
$("correctButton").onclick = () => {
  if (!state.token) return;
  state.correctionToken = {...state.token};
  $("correctError").hidden = true;
  $("saveReading").disabled = false; $("saveReading").textContent = "保存注音";
  $("correctTitle").textContent = state.token.language === "zh" ? "修正粤拼" : "修正注音";
  $("correctReading").placeholder = state.token.language === "zh" ? "例如 ngo5；留空恢复自动读音" : "输入平假名或 IPA，留空恢复自动注音";
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
  if (!state.correctionToken || $("saveReading").disabled) return;
  $("saveReading").disabled = true; $("saveReading").textContent = "正在保存…";
  $("correctError").hidden = true;
  action("correct", {
    ...state.correctionToken,
    reading: $("correctReading").value,
    readingSystem: state.correctionToken.readingSystem || "default",
  });
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
  return !target.closest("#playerVolumePanel") && !editing && !e.isComposing && !document.querySelector("dialog[open]");
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
  Theme.restore(p.theme);
  if (p.ruby !== undefined) $("rubyToggle").checked = p.ruby;
  // 旧配置缺少此字段时维持默认关闭，先读完全部偏好再持久化。
  state.romaji = p.romaji === true;
  $("romajiToggle").checked = state.romaji;
  state.cantonese = p.cantonese === true;
  $("cantoneseToggle").checked = state.cantonese;
  if (p.translation !== undefined)
    $("translationToggle").checked = p.translation;
  if (p.size) $("fontSize").value = p.size;
  state.lyricFont = typeof p.lyricFont === "string" ? p.lyricFont : "";
  applyLyricFont();
  if (p.follow !== undefined) $("autoFollow").checked = p.follow;
  if (["advance", "center"].includes(p.followMode)) $("followMode").value = p.followMode;
  for (const key of ["playOnLyricSeek", "resumeAfterBrowse"]) {
    if (typeof p[key] === "boolean") state[key] = p[key];
    $(key).checked = state[key];
  }
  setVersionsCollapsed(p.collapsed?.versionsGroup ?? true);
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
    Theme.syncFrame();
    backend.initialize();
  });
}
scheduleFrame();

$("practiceButton").onclick = () => {
  action("practice");
};
