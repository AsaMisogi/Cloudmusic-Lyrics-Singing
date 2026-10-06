/* 通过真实 DOM 交互验证行为；等待只用于让动画结束，不替代断言。 */
(async () => {
  const checks = [], actions = [];
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const check = (name, passed) => checks.push({check: name, passed: !!passed});
  window.backend = {action: (name, raw) => actions.push([name, JSON.parse(raw)])};
  // 首次引导、路径修改与重启确认使用正式 DOM，假后端不影响真实网易云。
  const directory = 'C:\\音乐工具\\网易云';
  onEvent('clientSettings', {directory, setup: true});
  check('首次路径引导显示自动识别的目录', $('clientPathDialog').open && $('clientPathInput').value === directory);
  $('cancelClientPath').click();
  check('跳过路径引导仍可使用工具', !$('clientPathDialog').open && actions.length === 0);
  $('moreButton').click(); $('editClientPath').click();
  onEvent('clientPathSelected', {directory: 'D:\\CloudMusic'});
  $('saveClientPath').click();
  check('设置中修改路径提交后等待保存回执', actions.at(-1)[0] === 'saveClientPath' && actions.at(-1)[1] === 'D:\\CloudMusic' && $('clientPathDialog').open);
  onEvent('clientPathError', {message: '此路径下没有 cloudmusic.exe'});
  check('无效路径留在弹窗内显示明确错误', $('clientPathDialog').open && !$('clientPathError').hidden && $('clientPathInput').getAttribute('aria-invalid') === 'true');
  onEvent('clientSettings', {directory: 'D:\\CloudMusic', saved: true});
  check('保存成功关闭引导并更新设置目录', !$('clientPathDialog').open && $('clientDirectorySummary').textContent === 'D:\\CloudMusic');
  $('toolsDialog').close();
  onEvent('clientStatus', {busy: true});
  onEvent('clientRestartRequired', {directory});
  check('连接期间禁用重复操作并显示重启确认', $('connectCloud').disabled && $('clientRestartDialog').open);
  $('cancelClientRestart').click();
  check('取消重启只发送取消指令', actions.at(-1)[0] === 'confirmClientRestart' && actions.at(-1)[1] === false);
  onEvent('clientRestartRequired', {directory});
  $('clientRestartDialog').dispatchEvent(new Event('cancel')); $('clientRestartDialog').close();
  check('Esc 路径同样取消重启', actions.at(-1)[1] === false);
  onEvent('clientRestartRequired', {directory}); $('confirmClientRestart').click();
  check('确认后发送重启指令并关闭弹窗', actions.at(-1)[1] === true && !$('clientRestartDialog').open);
  onEvent('clientStatus', {busy: false});
  check('连接结束恢复路径设置和连接按钮', !$('connectCloud').disabled && !$('editClientPath').disabled);
  const lines = Array.from({length: 24}, (_, i) => ({start: i * 3000, end: (i + 1) * 3000,
    text: 'Sing along with the morning light', translation: '跟着清晨的光一起唱。', timing: 'line', words: []}));
  onEvent('mode', {mode: 'local'});
  onEvent('lyrics', {lines, source: '交互验收示例'});
  updatePlayback({position: 0, duration: 72000, playing: false, canSeek: true});
  check('默认启用自动跟随', $('autoFollow').checked);
  check('歌词行不显示序号', document.querySelector('.lyric-number') === null);
  $('followMode').value = 'center'; $('followMode').dispatchEvent(new Event('change'));
  await wait(450);
  const centered = () => {
    const a = lyricRows[state.active].getBoundingClientRect(), b = $('lyricViewport').getBoundingClientRect();
    return Math.abs((a.top + a.bottom - b.top - b.bottom) / 2) < 3;
  };
  check('第一句可以居中', centered());
  const firstGeometry = {row: lyricRows[0].getBoundingClientRect().toJSON(), viewport: $('lyricViewport').getBoundingClientRect().toJSON(), scroll: $('lyricViewport').scrollTop, target: state.scrollTarget};
  updatePlayback({position: 69000, duration: 72000, playing: false, canSeek: true});
  await wait(650);
  check('最后一句可以居中', centered());
  $('autoFollow').click();
  const before = $('lyricViewport').scrollTop;
  updatePlayback({position: 18000, duration: 72000, playing: false, canSeek: true});
  await wait(200);
  check('关闭跟随后不自动滚动', Math.abs($('lyricViewport').scrollTop - before) < 1);
  $('autoFollow').click();
  $('followMode').value = 'advance'; $('followMode').dispatchEvent(new Event('change'));
  await wait(650);
  const row = lyricRows[6].getBoundingClientRect(), viewport = $('lyricViewport').getBoundingClientRect();
  check('向下跟随让当前行可见', row.top >= viewport.top - 2 && row.top < viewport.bottom);
  $('lyricViewport').dispatchEvent(new WheelEvent('wheel', {deltaY: 100}));
  check('默认手动浏览不自动返回', state.follow && state.resumeFollowAt === Infinity);
  $('resumeAfterBrowse').click();
  check('设置可启用四秒自动返回', Number.isFinite(state.resumeFollowAt) && state.resumeFollowAt > performance.now());
  state.resumeFollowAt = performance.now() + 80;
  await wait(250);
  check('暂缓后自动恢复', state.resumeFollowAt === 0);
  check('默认歌词点击自动播放', state.playOnLyricSeek);
  lyricRows[2].click();
  check('歌词跳转提交有序播放指令', actions.at(-1)[0] === 'seekAndPlay' && actions.at(-1)[1] === 6000);
  $('playOnLyricSeek').click();
  lyricRows[3].click();
  check('关闭后仅定位', actions.at(-1)[0] === 'seek' && actions.at(-1)[1] === 9000);
  state.pendingSeek = null;
  const expandedHeight = $('lyricViewport').clientHeight;
  for (const [button] of foldGroups) $(button).click();
  await wait(100);
  const saved = JSON.parse(localStorage.getItem('utatomo-display'));
  check('折叠释放歌词空间且持久保存', $('lyricViewport').clientHeight > expandedHeight + 70 && Object.values(saved.collapsed).every(Boolean));
  check('全局交互偏好持久保存', saved.playOnLyricSeek === false && saved.resumeAfterBrowse === true);
  check('折叠后设置和搜索仍可用', $('moreButton').getBoundingClientRect().height > 0 && $('searchButton').getBoundingClientRect().height > 0);
  for (const [button] of foldGroups) $(button).click();
  onEvent('mode', {mode: 'cloud'});
  check('云同步侧栏无多余滚动条', document.querySelector('.sidebar').scrollHeight <= document.querySelector('.sidebar').clientHeight);
  onEvent('mode', {mode: 'local'});
  $('quickFontSize').value = 52; $('quickFontSize').dispatchEvent(new Event('input'));
  check('主界面字号实时生效', $('fontSize').value === '52' && parseFloat(getComputedStyle(lyricRows[0].querySelector('.lyric-original')).fontSize) >= 49);
  onEvent('versions', {songs: [{id: 1, title: 'Studio', artist: 'Singer'}, {id: 2, title: 'Live', artist: 'Singer'}], songId: 1,
    versions: [{id: 'yrc', label: '逐字'}, {id: 'lrc', label: '逐行'}], selected: 'yrc'});
  $('songVersion').value = '2'; $('songVersion').dispatchEvent(new Event('change'));
  $('lyricVersion').value = 'lrc'; $('lyricVersion').dispatchEvent(new Event('change'));
  check('可以切换歌曲及歌词时间轴版本', actions.some(a => a[0] === 'selectSong' && a[1].id === '2') && actions.some(a => a[0] === 'selectVersion' && a[1] === 'lrc'));
  $('seek').value = 12510; $('seek').dispatchEvent(new Event('input')); $('seek').dispatchEvent(new Event('change'));
  check('进度条释放提交毫秒跳转', actions.some(a => a[0] === 'seek' && a[1] === 12510));
  updatePlayback({position: 1000, duration: 72000, playing: false, canSeek: true});
  check('旧快照不会立即拉回拖动位置', state.position === 12510);
  updatePlayback({position: 12510, duration: 72000, playing: false, canSeek: true});
  check('客户端确认位置后退出预览', state.pendingSeek === null);
  $('quickFontSize').value = 34; $('quickFontSize').dispatchEvent(new Event('input'));
  // 日语 ruby 与原文字重必须保持一致，切换高亮不能重新换行或改变行高。
  const japanese = {start:0,end:5000,text:'明日へ光を追いかけて',timing:'word',translation:'向着明天追寻光芒',
    tokens:[{text:'明日',reading:'あす',language:'ja'}, {text:'へ光を追いかけて',reading:'',language:'ja'}],
    words:[{text:'明日',start:0,end:1000},{text:'へ光を追いかけて',start:1500,end:5000}]};
  onEvent('lyrics', {lines:[japanese,{...japanese,start:5000,end:10000}], source:'日语注音与动画验收'});
  updatePlayback({position:250,duration:10000,playing:false,canSeek:true});
  updateHighlight(250);
  const rubyRow = lyricRows[0], original = rubyRow.querySelector('.lyric-original'), rt = rubyRow.querySelector('rt');
  const activeGeometry = [rubyRow.offsetHeight, original.offsetWidth, getComputedStyle(original).fontWeight, getComputedStyle(rt).fontWeight];
  updateHighlight(5500);
  check('切行时日文原文和注音的字重及尺寸保持不变', JSON.stringify(activeGeometry) === JSON.stringify(
    [rubyRow.offsetHeight, original.offsetWidth, getComputedStyle(original).fontWeight, getComputedStyle(rt).fontWeight]));
  updateHighlight(500);
  check('逐字时间连续填充半个词', Math.abs(parseFloat(rubyRow.querySelector('.token-base').style.getPropertyValue('--fill'))-50)<.01);
  updateHighlight(1250);
  const gapFills = [...rubyRow.querySelectorAll('.token-base')].map(t=>parseFloat(t.style.getPropertyValue('--fill')));
  check('字词间停顿保留真实时间', gapFills[0]===100 && gapFills[1]===0);
  // 有重叠的逐字时间分别作用于自己的字词，不将后词的着色提前挤进前词。
  state.lines[0].words = [{text:'明日',start:0,end:2000},{text:'へ光を追いかけて',start:1000,end:5000}];
  updateHighlight(1500);
  const overlapFills = [...rubyRow.querySelectorAll('.token-base')].map(t=>parseFloat(t.style.getPropertyValue('--fill')));
  check('重叠逐字时间分别着色', Math.abs(overlapFills[0]-75)<.01 && Math.abs(overlapFills[1]-12.5)<.01);
  const sampleClock = new PlaybackClock();
  let previous = -1, reversals = 0, maxFrameStep = 0;
  for(let t=0;t<=3000;t+=10) {
    if(t%100===0) sampleClock.update({position:Math.floor(t/500)*500,playing:true,duration:10000},t);
    const p=sampleClock.read(t);
    if(previous>=0) { if(p<previous) reversals++; maxFrameStep=Math.max(maxFrameStep,p-previous); }
    previous=p;
  }
  check('量化快照不让行背景往回跳或字词突跳', reversals===0 && maxFrameStep<14);
  const parts = text => rubyParts({text,reading:({'逃げ出し':'にげだし','取り戻す':'とりもどす','飛び出し':'とびだし','お祝い':'おいわい','明日':'あした'})[text],language:'ja'});
  check('逃げ出し逐段 ruby 不重复内部假名', JSON.stringify(parts('逃げ出し')) === JSON.stringify(
    [{text:'逃',reading:'に'},{text:'げ',reading:''},{text:'出',reading:'だ'},{text:'し',reading:''}]));
  check('取り戻す和飛び出し保留内部假名', parts('取り戻す').map(p=>p.reading).join('|')==='と||もど|' && parts('飛び出し').map(p=>p.reading).join('|')==='と||だ|');
  check('前后假名不重复注音', parts('お祝い').map(p=>p.reading).join('|')==='|いわ|');
  check('熟字训保持整组不硬拆单汉字', parts('明日').length===1 && parts('明日')[0].reading==='あした');
  const token = {text:'逃げ出し',reading:'にげだし',language:'ja',lemma:'逃げ出す',source:'本句用户校正'};
  onEvent('lyrics',{lines:[{start:0,end:5000,text:'逃げ出し',tokens:[token],words:[],timing:'line'}]});
  const baseSpans=[...lyricRows[0].querySelectorAll('.token-base')];
  check('拆分后字符位置连续且原文不丢失', baseSpans.map(s=>s.textContent).join('')==='逃げ出し' && baseSpans.map(s=>s.dataset.start).join(',')==='0,1,2,3');
  setDictionary(true);
  lyricRows[0].querySelectorAll('.token-base')[2].click();
  check('分开注音仍查询整个词的原形', actions.at(-1)?.[0]==='dictionary' && actions.at(-1)?.[1]?.lemma==='逃げ出す');
  setDictionary(false);
  onEvent('lyrics',{source:'同版本替代时间轴验收',lines:[
    {start:49100,end:52200,text:'Beautiful world',timing:'line',words:[]},
    {start:52200,end:57460,text:'迷わず君だけを見つめている',timing:'line',words:[]}
  ]});
  updatePlayback({position:51000,duration:310000,playing:false,canSeek:true});
  updateHighlight(51000);
  check('51秒仍在唱 Beautiful world', state.active===0);
  updateHighlight(52200);
  check('52.2秒才进入下一句', state.active===1);
  updatePlayback({position:51000,duration:310000,playing:false,canSeek:true});
  // 直接采样 rAF 间隔，以证据确认是否仍被引擎锁在 60 FPS。
  let stamps = [];
  await new Promise(resolve => {
    const measure = stamp => { stamps.push(stamp); if (stamp - stamps[0] < 800) requestAnimationFrame(measure); else resolve(); };
    requestAnimationFrame(measure);
  });
  const fps = (stamps.length - 1) * 1000 / (stamps.at(-1) - stamps[0]);
  check('最小窗口没有水平溢出', document.documentElement.scrollWidth <= innerWidth);
  check('最小窗口保留歌词空间', $('lyricViewport').clientHeight > 130);
  await wait(300);
  window.__uiResult = {checks, errors: window.__errors, firstGeometry, animationFramesPerSecond: Math.round(fps)};
})().catch(error => {window.__uiResult = {checks: [], errors: [String(error)]};});
