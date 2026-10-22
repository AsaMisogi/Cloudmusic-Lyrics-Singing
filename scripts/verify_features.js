/* 经真实 WebChannel、语言线程、SQLite 与静音 QMediaPlayer 验证完整操作链。 */
(async () => {
  const checks = [], wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed) => checks.push({check:name, passed:!!passed});
  async function until(name, condition) {
    const deadline = performance.now()+4500;
    while (!condition() && performance.now()<deadline) await wait(50);
    check(name, condition());
    if (!condition()) throw Error(name + ' 未完成');
  }
  async function capture(name) { window.__featureCapture=name; await wait(240); window.__featureCapture=null; }
  const rowFor = key => [...$('libraryTracks').children].find(row => row.dataset.trackKey===key);
  await until('真实界面桥接已连接且默认关闭粤拼', ()=>!!window.backend && !state.cantonese);
  $('recentButton').click();
  await until('导入曲库不会冒充最近播放', ()=>libraryUI.data.options?.view==='recent' && libraryUI.data.total===0);
  $('favoritesTab').click();
  await until('收藏读取两首本地与一首网易云曲目', ()=>libraryUI.data.options?.view==='favorites' && libraryUI.data.total===3);
  rowFor(featureInputs.first).querySelector('.track-play').click();
  await until('列表点击实际打开并播放第一首本地音频', ()=>libraryUI.current?.key===featureInputs.first && state.mode==='local' && state.playing && state.duration===40000);
  rowFor(featureInputs.second).querySelector('.track-play').click();
  await until('列表快速切到第二首并实际播放', ()=>libraryUI.current?.key===featureInputs.second && state.playing);
  await wait(250);
  $('historyTab').click();
  await until('实际播放两首后历史去重保存', ()=>libraryUI.data.options?.view==='recent' && libraryUI.data.total===2);
  await capture('recent');
  $('librarySearchInput').value='粤语'; $('librarySearchInput').dispatchEvent(new Event('input'));
  await until('后端搜索返回指定本地歌曲', ()=>libraryUI.data.options?.query==='粤语' && libraryUI.data.total===1 && libraryUI.data.tracks[0].key===featureInputs.first);
  $('favoritesTab').click();
  await until('返回曲库清空旧搜索', ()=>libraryUI.data.options?.view==='favorites' && !libraryUI.data.options.query);
  $('createPlaylist').click(); $('playlistNameInput').value='每天一首'; $('savePlaylistName').click();
  await until('创建歌单经事务成功后显示空歌单', ()=>!$('playlistNameDialog').open && libraryUI.data.options?.view==='playlist' && libraryUI.data.playlists.length===1);
  $('renamePlaylist').click(); $('playlistNameInput').value='每天一首 · 已改名'; $('savePlaylistName').click();
  await until('重命名歌单真实保存', ()=>!$('playlistNameDialog').open && libraryUI.data.playlists[0]?.name==='每天一首 · 已改名');
  $('historyTab').click();
  await until('返回历史继续选择歌曲', ()=>libraryUI.data.options?.view==='recent' && libraryUI.data.total===2);
  rowFor(featureInputs.first).querySelector('[data-track-action="playlist"]').click();
  $('playlistPickerList').querySelector('button').click();
  await until('最近播放歌曲成功加入歌单', ()=>!$('playlistPickerDialog').open && libraryUI.data.playlists[0]?.count===1);
  $('favoritesTab').click();
  await until('收藏视图已载入', ()=>libraryUI.data.options?.view==='favorites');
  $('playlistList').querySelector('button').click();
  await until('歌单可读取所选本地歌曲', ()=>libraryUI.data.options?.view==='playlist' && libraryUI.data.total===1);
  $('importLibraryAudio').click();
  await until('本地多选入口通过原生选择框添加引用', ()=>libraryUI.data.total===2);
  $('addCloudTrack').click(); $('cloudAddInput').value='789'; $('cloudAddSearch').click();
  await until('歌曲 ID 经后台服务查得元数据', ()=>!!$('cloudAddResults').querySelector('button'));
  $('cloudAddResults').querySelector('button').click();
  await until('网易云歌曲保存为同一歌单成员', ()=>!$('cloudAddDialog').open && libraryUI.data.total===3 && libraryUI.data.tracks.some(track=>track.songId==='789'));
  await capture('collection');
  $('libraryDialog').close();
  // 回到中文本地歌，音频继续真实播放；注音修正不重载播放器。
  action('libraryPlay',{key:featureInputs.first});
  await until('中文原文由真实语言线程生成粤拼候选', ()=>state.lines[0]?.text==='我會唱歌' && !!state.lines[0].cantoneseTokens);
  await until('中文歌曲播放器已就绪并实际播放', ()=>state.playing && state.duration===40000);
  $('cantoneseToggle').click(); setDictionary(true);
  check('开启粤拼显示离线结果，英文混行仍显示 IPA', lyricRows[0].querySelector('rt').textContent==='ngo5' && state.lines[2].cantoneseTokens.some(token=>token.language==='en' && !!token.reading));
  lyricRows[0].querySelector('.token').click(); $('correctButton').click();
  const keptRow=lyricRows[0]; state.resumeFollowAt=Infinity; state.scrollTarget=null;
  $('correctReading').value='ngo4'; $('saveReading').click();
  await until('粤拼修正经后台原子保存回到词典', ()=>!$('correctDialog').open && lyricRows[0].querySelector('rt').textContent==='ngo4');
  check('真实修正保留行对象、浏览暂停和播放', lyricRows[0]===keptRow && state.resumeFollowAt===Infinity && state.playing);
  $('correctButton').click(); $('correctReading').value=''; $('saveReading').click();
  await until('留空真实恢复自动粤拼', ()=>!$('correctDialog').open && lyricRows[0].querySelector('rt').textContent==='ngo5');
  $('toast').hidden=true;
  await capture('cantonese');
  // 从实际 SQLite 验证红心只管理最爱，取消不丢歌单或曲库成员。
  $('favoriteCurrent').click();
  await until('当前歌红心经事务加入最爱', ()=>libraryUI.current?.favorite===true);
  $('libraryButton').click(); $('lovedTracks').click();
  await until('最爱固定分类读取真实红心曲目', ()=>libraryUI.data.options?.view==='loved' && libraryUI.data.total===1);
  rowFor(featureInputs.first).querySelector('[data-track-action="favorite"]').click();
  await until('最爱取消后即时移出当前分类', ()=>libraryUI.data.options?.view==='loved' && libraryUI.data.total===0);
  $('allFavorites').click();
  await until('取消红心后歌曲仍保留全部曲目', ()=>libraryUI.data.options?.view==='favorites' && libraryUI.data.tracks.some(t=>t.key===featureInputs.first));
  check('取消最爱保留原歌单成员', libraryUI.data.playlists[0]?.count===3);
  $('libraryDialog').close();
  $('playlistCurrent').click(); $('playlistPickerList').querySelector('button').click();
  await until('封面下快捷歌单真实保存且不会自动红心', ()=>!$('playlistPickerDialog').open && libraryUI.current?.favorite===false);
  await until('字体下拉包含真实 Qt 本机字体', ()=>$('lyricFont').options.length>10);
  $('lyricFont').value='Microsoft YaHei'; $('lyricFont').dispatchEvent(new Event('change'));
  check('真实本机字体选择即时应用歌词', getComputedStyle(lyricRows[0].querySelector('.lyric-original')).fontFamily.startsWith('"Microsoft YaHei"'));
  // 将完整报告保存在 sessionStorage，重载走正式初始化路径检查显示偏好。
  window.__featureBeforeReload=checks;
  sessionStorage.setItem('feature-checks',JSON.stringify(checks));
  window.__featureReadyToReload=true;
})().catch(error=>{ window.__featureResult={checks:[],errors:[String(error),...window.__errors]}; });
