/* 曲库是播放入口，歌词搜索仍只负责换歌词。
 * 列表分页由后端执行；用户输入和服务文字只经 textContent 写入。
 * 收藏、歌单和删除均等待 SQLite 提交回执，不以按钮点击冒充保存成功。
 */
"use strict";
const libraryUI = {
  options: {view: "recent", source: "all", query: "", page: 0},
  data: {tracks: [], playlists: [], total: 0, page: 0, pageSize: 50},
  current: null, unavailable: "", pending: null, pickedTrack: null, pickingCurrent: false,
  renameId: "", searchQuery: "", searchTimer: null, confirm: null,
};
function libraryIcon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", "#i-" + name); svg.append(use); return svg;
}
function libraryFeedback(message, error = false) {
  $("libraryFeedback").textContent = message;
  $("libraryFeedback").hidden = !message;
  $("libraryFeedback").classList.toggle("inline-error", error);
  if (!$("libraryDialog").open) toast(message, error);
}
function queryLibrary(resetPage = false) {
  if (resetPage) libraryUI.options.page = 0;
  if (!libraryUI.unavailable) action("libraryQuery", libraryUI.options);
}
function openLibrary(view) {
  libraryUI.options = {...libraryUI.options, view, query: "", page: 0, playlistId: ""};
  $("librarySearchInput").value = "";
  libraryFeedback(libraryUI.unavailable);
  renderLibrary();
  if (!$("libraryDialog").open) $("libraryDialog").showModal();
  queryLibrary();
  $("librarySearchInput").focus();
}
function libraryMutate(name, value, dialog) {
  libraryUI.pending = {name, dialog};
  if (dialog === "playlistNameDialog") $("savePlaylistName").disabled = true;
  if (dialog === "libraryConfirmDialog") $("libraryConfirmAction").disabled = true;
  action(name, value);
}
function renderLibrary() {
  const {options, data} = libraryUI;
  const recent = options.view === "recent", playlist = options.view === "playlist", loved = options.view === "loved";
  const selected = data.playlists.find(p => p.id === options.playlistId);
  $("libraryTitle").textContent = recent ? "最近播放" : playlist ? selected?.name || "我的歌单" : loved ? "最爱" : "全部曲目";
  $("historyTab").setAttribute("aria-selected", String(recent));
  $("favoritesTab").setAttribute("aria-selected", String(!recent));
  $("historyTab").tabIndex = recent ? 0 : -1;
  $("favoritesTab").tabIndex = recent ? -1 : 0;
  $("playlistSidebar").hidden = recent;
  $("libraryBody").classList.toggle("has-playlists", !recent);
  $("clearHistory").hidden = !recent;
  $("renamePlaylist").hidden = $("deletePlaylist").hidden = !playlist;
  $("importLibraryAudio").hidden = $("addCloudTrack").hidden = recent;
  $("allFavorites").classList.toggle("selected", !playlist && !loved);
  $("allFavorites").setAttribute("aria-pressed", String(!playlist && !loved));
  $("lovedTracks").classList.toggle("selected", loved);
  $("lovedTracks").setAttribute("aria-pressed", String(loved));
  document.querySelectorAll("#sourceFilters button").forEach(button =>
    button.setAttribute("aria-pressed", String(button.dataset.source === options.source)));
  $("librarySummary").textContent = `${data.total} 首${options.query ? "匹配" : "歌曲"}`;
  $("playlistList").replaceChildren(...data.playlists.map(item => {
    const button = document.createElement("button");
    button.className = "playlist-item";
    button.classList.toggle("selected", item.id === options.playlistId);
    button.setAttribute("aria-pressed", String(item.id === options.playlistId));
    const name = document.createElement("span"), count = document.createElement("span");
    name.textContent = item.name; name.className = "playlist-name"; button.title = item.name;
    count.textContent = item.count; count.className = "nav-count";
    button.append(libraryIcon("list"), name, count);
    button.onclick = () => {
      libraryUI.options = {...options, view: "playlist", playlistId: item.id, page: 0};
      queryLibrary();
    };
    return button;
  }));
  renderLibraryTracks();
  const pages = Math.max(1, Math.ceil(data.total / data.pageSize));
  $("libraryPageLabel").textContent = data.total ? `第 ${data.page + 1} / ${pages} 页 · 每页最多 ${data.pageSize} 首` : "";
  $("libraryPrev").disabled = data.page <= 0;
  $("libraryNext").disabled = data.page + 1 >= pages;
  $("clearHistory").disabled = !data.total;
}
function renderLibraryTracks() {
  const {tracks} = libraryUI.data, container = $("libraryTracks");
  const focused = document.activeElement;
  const focusedKey = focused?.closest("[data-track-key]")?.dataset.trackKey;
  const focusedAction = focused?.dataset.trackAction;
  const fragment = document.createDocumentFragment();
  if (!tracks.length) {
    const empty = document.createElement("div"); empty.className = "library-empty";
    const heading = document.createElement("h3"), hint = document.createElement("p");
    if (libraryUI.options.query) {
      heading.textContent = "没有找到这首歌";
      hint.textContent = "试试更短的歌名、歌手或其他来源，也可以清空搜索。";
      const clear = document.createElement("button"); clear.className = "outline-button"; clear.textContent = "清空搜索";
      clear.onclick = () => { $("librarySearchInput").value = ""; libraryUI.options.query = ""; queryLibrary(true); };
      empty.append(heading, hint, clear);
    } else {
      const recent = libraryUI.options.view === "recent";
      const loved = libraryUI.options.view === "loved";
      heading.textContent = recent ? "从下一首歌开始记录" : loved ? "给喜欢的歌，一颗红心" : "把常练的歌，留在这里";
      hint.textContent = recent ? "实际播放过的本地歌曲和网易云歌曲会出现在这里，两种来源各保留最近 500 首。" : loved ? "在当前歌曲或曲目列表点击红心，即可加入最爱。" : "添加本地音频或网易云歌曲，也可以从最近播放中加入歌单。";
      empty.append(libraryIcon(recent ? "history" : "heart"), heading, hint);
      const start = document.createElement("button"); start.className = "outline-button";
      start.textContent = recent ? "打开本地音频" : loved ? "浏览全部曲目" : "添加本地歌曲";
      start.onclick = () => recent ? action("openAudio") : loved ? $("allFavorites").click() : action("libraryImport", {playlistId: activePlaylist()});
      empty.append(start);
    }
    fragment.append(empty);
  }
  for (const track of tracks) {
    const row = document.createElement("div"); row.className = "library-track";
    row.dataset.trackKey = track.key;
    const current = libraryUI.current?.key === track.key;
    row.classList.toggle("current-track", current);
    const play = document.createElement("button"); play.className = "track-play";
    play.dataset.trackAction = "play"; play.disabled = !track.available;
    play.setAttribute("aria-label", `播放 ${track.title} ${track.artist}`);
    const glyph = document.createElement("span"); glyph.className = "track-play-icon"; glyph.append(libraryIcon("play"));
    const text = document.createElement("span"); text.className = "track-text";
    const title = document.createElement("strong"); title.textContent = track.title;
    const subtitle = document.createElement("span"); subtitle.className = "track-subtitle";
    subtitle.textContent = [track.artist || (track.source === "local" ? "本地音频" : "网易云歌曲"), track.album,
      track.duration ? time(track.duration).slice(0, -4) : ""].filter(Boolean).join(" · ");
    text.append(title, subtitle);
    play.append(glyph, text); play.title = [track.title, track.artist, track.path || `网易云 ID ${track.songId}`].join("\n");
    play.onclick = () => { libraryFeedback("正在打开：" + track.title); action("libraryPlay", {key: track.key}); };
    const source = document.createElement("span"); source.className = "source-badge";
    source.textContent = track.source === "local" ? "本地" : "网易云";
    const status = document.createElement("span"); status.className = "track-status";
    status.textContent = current ? "当前曲目" : "";
    const controls = document.createElement("div"); controls.className = "track-row-actions";
    if (!track.available) {
      const unavailable = document.createElement("span"); unavailable.className = "track-unavailable";
      unavailable.textContent = track.source === "local" ? "文件已移动" : "缺少歌曲 ID";
      unavailable.title = track.source === "local" ? track.path : "直连网易云后播放一次，或通过歌曲链接加入收藏。";
      controls.append(unavailable);
      if (track.source === "local") {
        const relink = document.createElement("button"); relink.className = "text-button";
        relink.textContent = "重新定位"; relink.onclick = () => action("libraryRelink", {key: track.key});
        controls.append(relink);
      }
    }
    const favorite = document.createElement("button"); favorite.className = "icon-button small favorite-button";
    favorite.dataset.trackAction = "favorite"; favorite.setAttribute("aria-pressed", String(!!track.favorite));
    favorite.title = favorite.ariaLabel = `${track.favorite ? "取消最爱" : "加入最爱"} ${track.title}`;
    favorite.append(libraryIcon("heart"));
    favorite.onclick = () => action("libraryFavorite", {key: track.key, enabled: !track.favorite});
    const playlist = document.createElement("button"); playlist.className = "icon-button small";
    playlist.dataset.trackAction = "playlist"; playlist.title = playlist.ariaLabel = `将 ${track.title} 加入歌单`;
    playlist.append(libraryIcon("plus")); playlist.onclick = () => openPlaylistPicker(track);
    const remove = document.createElement("button"); remove.className = "icon-button small";
    remove.dataset.trackAction = "remove"; remove.textContent = "×";
    if (libraryUI.options.view === "favorites") { remove.replaceChildren(libraryIcon("trash")); remove.classList.add("danger-text"); }
    remove.title = remove.ariaLabel = libraryUI.options.view === "recent" ? "移除此播放记录" : libraryUI.options.view === "playlist" ? "从此歌单移除" : "从曲库移除";
    remove.onclick = () => confirmTrackRemoval(track);
    // 最爱视图用红心取消最爱；全局移除只在「全部曲目」出现，避免同一行双重移除。
    controls.append(favorite, playlist);
    if (libraryUI.options.view !== "loved") controls.append(remove);
    row.append(play, source, status, controls); fragment.append(row);
  }
  container.replaceChildren(fragment);
  if (focusedKey && focusedAction) {
    const row = [...container.children].find(row => row.dataset.trackKey === focusedKey);
    row?.querySelector(`[data-track-action="${focusedAction}"]`)?.focus({preventScroll: true});
  }
}
function activePlaylist() { return libraryUI.options.view === "playlist" ? libraryUI.options.playlistId : ""; }
function openPlaylistName(rename = false) {
  libraryUI.renameId = rename ? activePlaylist() : "";
  $("playlistNameTitle").textContent = rename ? "重命名歌单" : "新建歌单";
  $("playlistNameInput").value = rename ? libraryUI.data.playlists.find(p => p.id === libraryUI.renameId)?.name || "" : "";
  $("playlistNameError").hidden = true; $("savePlaylistName").disabled = false;
  $("playlistNameDialog").showModal(); $("playlistNameInput").focus();
}
function openPlaylistPicker(track, current = false) {
  libraryUI.pickedTrack = track;
  libraryUI.pickingCurrent = current;
  $("playlistPickerTrack").textContent = track.title;
  $("playlistPickerFeedback").hidden = true;
  renderPlaylistPicker(); $("playlistPickerDialog").showModal();
}
function renderPlaylistPicker() {
  $("playlistPickerList").replaceChildren(...libraryUI.data.playlists.map(item => {
    const button = document.createElement("button"); button.className = "playlist-choice";
    button.textContent = item.name; button.type = "button";
    button.onclick = () => libraryMutate("libraryMembership", {playlistId: item.id, key: libraryUI.pickedTrack.key, enabled: true, current: libraryUI.pickingCurrent}, "playlistPickerDialog");
    return button;
  }));
  if (!libraryUI.data.playlists.length) $("playlistPickerList").textContent = "还没有歌单，先建一个吧。";
}
function openLibraryConfirm(title, description, name, value) {
  libraryUI.confirm = {name, value};
  $("libraryConfirmTitle").textContent = title;
  $("libraryConfirmDescription").textContent = description;
  $("libraryConfirmAction").textContent = "确认";
  $("libraryConfirmAction").disabled = false; $("libraryConfirmError").hidden = true;
  $("libraryConfirmDialog").showModal();
}
function confirmTrackRemoval(track) {
  const view = libraryUI.options.view;
  if (view === "playlist") openLibraryConfirm("从歌单移除？", `只移除「${track.title}」与此歌单的关联，最爱、曲库和最近播放不变。`,
    "libraryMembership", {key: track.key, playlistId: activePlaylist(), enabled: false});
  else openLibraryConfirm(view === "recent" ? "移除此播放记录？" : "从曲库移除？",
    view === "recent" ? `移除「${track.title}」的最近播放记录，最爱和歌单不受影响。` : `将「${track.title}」从曲库、最爱及所有工具歌单中移除，保留最近播放记录，不删除音频文件。`,
    "libraryRemove", {key: track.key, historyOnly: view === "recent"});
}
function libraryEvents(kind, data) {
  if (kind === "library") {
    libraryUI.data = data; libraryUI.current = data.current;
    libraryUI.options = {...libraryUI.options, ...data.options, page: data.page};
    $("favoriteCurrent").disabled = !data.current;
    $("playlistCurrent").disabled = !data.current;
    $("favoriteCurrent").setAttribute("aria-pressed", String(!!data.current?.favorite));
    $("favoriteCurrentLabel").textContent = "最爱";
    $("favoriteCurrent").title = data.current?.favorite ? "取消最爱（保留在曲库和歌单中）" : "将当前歌曲加入最爱";
    $("favoriteCurrent").setAttribute("aria-label", $("favoriteCurrent").title);
    $("recentCount").textContent = Object.values(data.recentCounts).reduce((a,b)=>a+b, 0);
    if ($("libraryDialog").open) renderLibrary();
    if ($("playlistPickerDialog").open) renderPlaylistPicker();
  } else if (kind === "librarySaved") {
    if (data.operation === "libraryFavorite") libraryFeedback("最爱已更新。取消红心不会移出曲库或歌单。");
    const pending = libraryUI.pending;
    if (pending?.name === data.operation) {
      $(pending.dialog)?.close(); libraryUI.pending = null;
      $("savePlaylistName").disabled = false; $("libraryConfirmAction").disabled = false;
      libraryFeedback(pending.name === "libraryMembership" ? "歌单已更新。" : "已保存。");
    }
  } else if (kind === "libraryUnavailable") {
    libraryUI.unavailable = data.message; libraryFeedback(data.message, true);
  } else if (kind === "libraryError") {
    libraryFeedback(data.message, true);
    const pending = libraryUI.pending;
    const affected = data.operation || data.task;
    // 网络搜索与歌单写入是独立操作，旧搜索失败不能取消正在保存的歌单。
    if (pending && (!affected || affected === pending.name)) {
      const errorId = pending.dialog === "playlistNameDialog" ? "playlistNameError" : pending.dialog === "libraryConfirmDialog" ? "libraryConfirmError" : "playlistPickerFeedback";
      $(errorId).textContent = data.message; $(errorId).hidden = false;
      libraryUI.pending = null; $("savePlaylistName").disabled = false; $("libraryConfirmAction").disabled = false;
    }
    $("cloudAddSearch").disabled = false;
    $("cloudAddFeedback").textContent = data.message;
    document.querySelectorAll(".cloud-add-track").forEach(button => button.disabled = false);
  } else if (kind === "libraryNotice") libraryFeedback(data.message);
  else if (kind === "playlistCreated") { /* 选择状态由随后的后端曲库快照统一更新。 */ }
  else if (kind === "libraryAdded") {
    $("cloudAddDialog").close(); libraryFeedback(data.message);
  } else if (kind === "librarySearch") {
    if (data.query !== libraryUI.searchQuery) return;
    $("cloudAddSearch").disabled = false;
    $("cloudAddFeedback").textContent = data.songs.length ? "选择歌曲加入曲库；不会立即播放或自动标为最爱。" : "没有找到歌曲，试试更短的歌名或歌曲 ID。";
    $("cloudAddResults").replaceChildren(...data.songs.map(song => {
      const button = document.createElement("button"); button.className = "search-result cloud-add-track"; button.type = "button";
      const title = document.createElement("strong"), subtitle = document.createElement("span");
      title.textContent = song.title; subtitle.textContent = `${song.artist} · ${song.album || ""} · ID ${song.songId || song.id}`;
      button.append(title, subtitle);
      button.onclick = () => {
        document.querySelectorAll(".cloud-add-track").forEach(button => button.disabled = true);
        $("cloudAddFeedback").textContent = "正在保存到曲库…";
        action("libraryAddCloud", {songId: String(song.songId || song.id), playlistId: activePlaylist()});
      };
      return button;
    }));
  }
}
$("recentButton").onclick = () => openLibrary("recent");
$("libraryButton").onclick = () => openLibrary("favorites");
$("historyTab").onclick = () => openLibrary("recent");
$("favoritesTab").onclick = () => openLibrary("favorites");
for (const id of ["historyTab", "favoritesTab"]) $(id).onkeydown = event => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault(); const next = id === "historyTab" ? "favoritesTab" : "historyTab";
  $(next).click(); $(next).focus();
};
$("allFavorites").onclick = () => { libraryUI.options.view = "favorites"; libraryUI.options.playlistId = ""; queryLibrary(true); };
$("lovedTracks").onclick = () => { libraryUI.options.view = "loved"; libraryUI.options.playlistId = ""; queryLibrary(true); };
$("librarySearchInput").oninput = () => {
  clearTimeout(libraryUI.searchTimer);
  libraryUI.searchTimer = setTimeout(() => { libraryUI.options.query = $("librarySearchInput").value; queryLibrary(true); }, 140);
};
document.querySelectorAll("#sourceFilters button").forEach(button => button.onclick = () => {
  libraryUI.options.source = button.dataset.source; queryLibrary(true);
});
$("libraryPrev").onclick = () => { libraryUI.options.page = Math.max(0, libraryUI.data.page - 1); queryLibrary(); };
$("libraryNext").onclick = () => { libraryUI.options.page = libraryUI.data.page + 1; queryLibrary(); };
$("createPlaylist").onclick = $("pickerCreatePlaylist").onclick = () => openPlaylistName();
$("renamePlaylist").onclick = () => openPlaylistName(true);
$("playlistNameForm").onsubmit = event => {
  event.preventDefault(); if ($("savePlaylistName").disabled) return;
  const name = $("playlistNameInput").value.trim();
  if (!name) { $("playlistNameError").textContent = "请填写歌单名称。"; $("playlistNameError").hidden = false; return; }
  libraryMutate(libraryUI.renameId ? "libraryRenamePlaylist" : "libraryCreatePlaylist",
    {id: libraryUI.renameId, name, select: !$("playlistPickerDialog").open}, "playlistNameDialog");
};
$("libraryConfirmAction").onclick = () => {
  if (!libraryUI.confirm || $("libraryConfirmAction").disabled) return;
  libraryMutate(libraryUI.confirm.name, libraryUI.confirm.value, "libraryConfirmDialog");
};
$("deletePlaylist").onclick = () => openLibraryConfirm("删除这个歌单？", "歌单中的收藏、播放记录和音频文件不会删除。",
  "libraryDeletePlaylist", {id: activePlaylist()});
$("clearHistory").onclick = () => openLibraryConfirm("清空最近播放？", "只清空当前来源的播放记录，不影响曲库收藏或歌单。",
  "libraryClearHistory", {source: libraryUI.options.source});
$("importLibraryAudio").onclick = () => action("libraryImport", {playlistId: activePlaylist()});
$("favoriteCurrent").onclick = () => {
  const current = libraryUI.current;
  if (current) action("libraryFavorite", {key: current.favorite ? current.key : "", enabled: !current.favorite});
};
$("playlistCurrent").onclick = () => {
  if (libraryUI.current) openPlaylistPicker(libraryUI.current, true);
};
$("libraryConnectCloud").onclick = () => { $("libraryDialog").close(); action("connectCloud"); };
$("addCloudTrack").onclick = () => {
  $("cloudAddResults").replaceChildren(); $("cloudAddFeedback").textContent = "加入本地曲库收藏，不修改网易云账号歌单。";
  $("cloudAddSearch").disabled = false; $("cloudAddDialog").showModal(); $("cloudAddInput").focus();
};
$("cloudAddForm").onsubmit = event => {
  event.preventDefault(); if ($("cloudAddSearch").disabled) return;
  libraryUI.searchQuery = $("cloudAddInput").value.trim();
  if (!libraryUI.searchQuery) return;
  $("cloudAddSearch").disabled = true; $("cloudAddFeedback").textContent = "正在搜索网易云歌曲…";
  $("cloudAddResults").replaceChildren(); action("librarySearch", {query: libraryUI.searchQuery});
};
