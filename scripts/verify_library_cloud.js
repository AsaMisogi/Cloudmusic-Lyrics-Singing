/* 仅供已授权的真实网易云验收，调用正式曲库按钮与播放桥接。 */
(async () => {
  const checks=[], wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function until(name, predicate) {
    const end=performance.now()+12000;
    while (!predicate() && performance.now()<end) await wait(100);
    checks.push({check:name,passed:!!predicate()});
    if(!predicate()) throw Error(name+' 未完成');
  }
  const rowFor = key => [...$('libraryTracks').children].find(row=>row.dataset.trackKey===key);
  await until('网易云真实快照到达界面', ()=>!!libraryUI.current);
  $('libraryButton').click();
  await until('曲库列出测试歌曲和原曲', ()=>!!rowFor(cloudTest.target) && !!rowFor(cloudTest.original));
  rowFor(cloudTest.target).querySelector('.track-play').click();
  await until('点击曲库按钮让网易云实际切歌并播放', ()=>libraryUI.current?.key===cloudTest.target && state.playing);
  $('historyTab').click();
  await until('真实云端播放进入最近播放且使用真实 ID', ()=>libraryUI.data.options?.view==='recent' && libraryUI.data.tracks.some(t=>t.key===cloudTest.target && t.available));
  $('favoritesTab').click();
  await until('收藏视图仍保留原曲', ()=>!!rowFor(cloudTest.original));
  rowFor(cloudTest.original).querySelector('.track-play').click();
  await until('从收藏实际切回原曲', ()=>libraryUI.current?.key===cloudTest.original && state.playing);
  if (cloudTest.initial.canSeek) action('seek',cloudTest.initial.position);
  if (!cloudTest.initial.playing) { action('toggle'); await until('恢复原暂停状态',()=>!state.playing); }
  window.__cloudLibraryResult={checks,errors:window.__errors};
})().catch(error=>{window.__cloudLibraryResult={checks:[{check:'真实云端切歌完整路径',passed:false}],errors:[String(error),...window.__errors]};});
