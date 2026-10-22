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
  // 原生按键另由 verify_shortcuts.py 覆盖；此处补充重复和输入法标志。
  $('followMode').focus();
  const countBefore = actions.length;
  const heldSpace = new KeyboardEvent('keydown', {code:'Space',key:' ',repeat:true,bubbles:true,cancelable:true});
  $('followMode').dispatchEvent(heldSpace);
  check('长按空格取消默认行为且不重复切换', heldSpace.defaultPrevented && actions.length === countBefore);
  $('followMode').dispatchEvent(new KeyboardEvent('keydown', {code:'Space',key:' ',isComposing:true,bubbles:true,cancelable:true}));
  check('输入法组合期间不触发播放', actions.length === countBefore);
  const editor = document.createElement('div'); editor.contentEditable = 'true'; document.body.append(editor);
  editor.dispatchEvent(new KeyboardEvent('keydown', {code:'Space',key:' ',bubbles:true,cancelable:true}));
  check('可编辑内容正常接收空格', actions.length === countBefore);
  editor.remove();
  // 罗马音只改变显示，保持词汇边界、当前行、逐字时间与用户校正所需的假名。
  check('日语罗马音默认关闭', !state.romaji && !$('romajiToggle').checked);
  const romanTokens=[{text:'逃げ出し',reading:'にげだし',romaji:'nigedashi',language:'ja',lemma:'逃げ出す'},
    {text:'コーヒー',reading:'',romaji:'koohii',language:'ja',lemma:'コーヒー'},
    {text:'Sing',reading:'sɪŋ',romaji:'',language:'en',lemma:'sing'}];
  onEvent('lyrics',{lines:[{start:0,end:6000,text:'逃げ出しコーヒーSing',tokens:romanTokens,
    timing:'word',words:[{text:'逃げ出し',start:0,end:2000},{text:'コーヒー',start:2000,end:4000},{text:'Sing',start:4000,end:6000}]}]});
  updatePlayback({position:1000,duration:6000,playing:false,canSeek:true}); updateHighlight(1000);
  const keptRow=lyricRows[0], englishRuby=keptRow.querySelector('.token.en ruby');
  const readingBefore=romanTokens[0].reading, savedLoop=state.loop;
  state.resumeFollowAt=performance.now()+60000; state.scrollTarget=null;
  const savedResume=state.resumeFollowAt;
  $('romajiToggle').click();
  check('开启后日语整词和纯假名显示罗马音', [...keptRow.querySelectorAll('rt')].map(t=>t.textContent).join('|')==='nigedashi|koohii|sɪŋ');
  check('切换不改英语音标或词汇 DOM', keptRow.querySelector('.token.en ruby')===englishRuby);
  check('罗马音按原字符范围进行逐字高亮', Math.abs(parseFloat(keptRow.querySelector('.token-base').style.getPropertyValue('--fill'))-50)<.01);
  check('切换保留歌词行、原始读音和循环状态', lyricRows[0]===keptRow && romanTokens[0].reading===readingBefore && state.loop===savedLoop);
  check('切换保留手动浏览暂停且不恢复跟随', state.resumeFollowAt===savedResume && state.scrollTarget===null);
  check('罗马音偏好持久保存', JSON.parse(localStorage.getItem('utatomo-display')).romaji===true);
  setDictionary(true); keptRow.querySelector('.token-base').click();
  check('罗马音模式查词仍使用完整词原形', actions.at(-1)?.[0]==='dictionary' && actions.at(-1)?.[1]?.lemma==='逃げ出す' && $('dictReading').textContent==='nigedashi');
  $('correctButton').click();
  check('注音修正仍编辑原始假名', $('correctReading').value==='にげだし'); $('correctDialog').close();
  $('rubyToggle').checked=false; display();
  check('罗马音服从注音总开关', getComputedStyle(keptRow.querySelector('rt')).display==='none');
  $('rubyToggle').checked=true; display();
  $('romajiToggle').click();
  check('关闭后恢复原有假名分段和词典读音', [...keptRow.querySelectorAll('rt')].map(t=>t.textContent).join('|')==='に|だ|sɪŋ' && $('dictReading').textContent==='にげだし');
  check('关闭状态也保存且与英文独立', JSON.parse(localStorage.getItem('utatomo-display')).romaji===false && keptRow.querySelector('.token.en ruby')===englishRuby);
  setDictionary(false); state.resumeFollowAt=0;
  // 更新功能通过真实 Chromium DOM 验收，网络结果用固定事件代替，不打开浏览器。
  onEvent('appVersion', {version:'0.3.0'});
  check('当前版本来自后端', $('appVersion').textContent==='v0.3.0' && $('sidebarVersion').textContent.includes('0.3.0'));
  $('github').click();
  check('GitHub 入口提交固定操作', actions.at(-1)?.[0]==='github');
  $('toolsDialog').showModal();
  $('checkUpdate').click();
  check('设置提供手动更新入口', actions.at(-1)?.[0]==='checkUpdate');
  onEvent('updateStatus', {busy:true});
  const updateCount=actions.length; $('checkUpdate').click();
  check('检查中禁用按钮并避免重复请求', $('checkUpdate').disabled && actions.length===updateCount && $('checkUpdate').textContent==='检查中…');
  onEvent('updateStatus', {busy:false});
  onEvent('updateResult', {status:'current',current:'0.3.0',version:'0.3.0',manual:true});
  check('无更新显示版本结果且恢复按钮', !$('checkUpdate').disabled && $('updateFeedback').textContent.includes('0.3.0') && !$('updateDialog').open);
  onEvent('updateResult', {status:'error',message:'网络不可用，请重试。',manual:true});
  check('手动失败显示原因并允许重试', $('updateFeedback').textContent.includes('网络不可用') && !$('checkUpdate').disabled);
  $('releasePage').click();
  check('失败时仍可查看发布页', actions.at(-1)?.[0]==='releases');
  const available={status:'available',current:'0.3.0',version:'0.4.0',manual:true};
  onEvent('updateResult', available);
  check('手动发现新版本从设置切换到更新弹窗', !$('toolsDialog').open && $('updateDialog').open && $('updateDescription').textContent.includes('0.4.0'));
  const laterCount=actions.length; $('laterUpdate').click();
  check('稍后更新不打开浏览器', !$('updateDialog').open && actions.length===laterCount);
  $('clientPathDialog').showModal();
  onEvent('updateResult', {...available,manual:false});
  check('自动提示不会覆盖路径引导', $('clientPathDialog').open && !$('updateDialog').open);
  $('clientPathDialog').close(); await wait(30);
  check('引导关闭后自动显示更新', $('updateDialog').open);
  $('downloadUpdate').click();
  check('下载按钮只请求后端打开 Release', !$('updateDialog').open && actions.at(-1)?.[0]==='openUpdate' && actions.at(-1)?.[1]===null);
  $('helpDialog').showModal(); onEvent('updateResult', {...available,manual:false});
  check('自动提示等待其他弹窗关闭', !$('updateDialog').open);
  $('helpDialog').close(); await wait(30);
  check('自动提示显示当前和最新版本', $('updateDialog').open && $('updateDescription').textContent.includes('0.3.0') && $('updateDescription').textContent.includes('0.4.0'));
  $('updateDialog').close();
  check('最小窗口 GitHub 入口可见', $('github').getBoundingClientRect().bottom<=innerHeight);
  // 在播放状态下打开设置/修正，统计真正的后台 DOM 写入，而非肉眼猜测帧率。
  onEvent('mode', {mode:'cloud'});
  onEvent('cloud', {connected:true, transport:'client', playing:true, position:1000, duration:40000, canSeek:true, hasTimeline:true});
  $('toolsDialog').showModal(); await wait(40);
  let backgroundWrites = 0;
  const backgroundObserver = new MutationObserver(items => backgroundWrites += items.length);
  backgroundObserver.observe(document.querySelector('main'), {subtree:true, childList:true, attributes:true, characterData:true});
  for (let i=0;i<6;i++) {
    onEvent('cloud', {connected:true, transport:'client', playing:true, position:1200+i*100, duration:40000, canSeek:true, hasTimeline:true});
    await wait(55);
  }
  backgroundObserver.disconnect();
  const modalEvidence={backgroundWrites, playing:state.playing, receivedPosition:lastPlayback.position};
  check('设置弹窗期间后台不持续改写 DOM，播放状态仍接收', modalOpen && backgroundWrites===0 && state.playing && lastPlayback.position===1700);
  check('所有模态遮罩移除 GPU 背景模糊', getComputedStyle($('toolsDialog'),'::backdrop').backdropFilter==='none');
  $('toolsDialog').close(); await wait(130);
  check('关闭弹窗立即恢复真实播放位置和按钮', !modalOpen && $('playGlyph').textContent==='Ⅱ' && $('position').textContent!==time(1000));
  onEvent('mode',{mode:'local'}); state.pendingSeek=null;
  updatePlayback({position:1000, duration:40000, playing:false, canSeek:true});
  check('粤拼默认关闭', !state.cantonese && !$('cantoneseToggle').checked);
  const yueTokens=[{text:'我',reading:'ngo5',language:'zh',readingSystem:'jyutping',scope:'yue',lineKey:'line',tokenStart:0,readingCandidates:[{reading:'ngo5',source:'粤拼词典'}]},
    {text:'唱',reading:'coeng3',language:'zh',readingSystem:'jyutping',scope:'yue',lineKey:'line',tokenStart:1},
    {text:'Sing',reading:'sɪŋ',language:'en',readingSystem:'default',scope:'yue',lineKey:'line',tokenStart:2}];
  const yueLine={start:0,end:5000,text:'我唱Sing',translation:'原有译文',tokens:[],cantoneseTokens:yueTokens,words:[],timing:'line'};
  onEvent('lyrics',{lines:[yueLine],source:'粤拼显示验收'});
  check('关闭粤拼时中文不显示日语猜读，英语音标仍在', [...$('lyrics').querySelectorAll('rt')].map(n=>n.textContent).join('|')==='sɪŋ');
  const yueRow=lyricRows[0]; state.resumeFollowAt=Infinity; state.scrollTarget=null;
  const yueLoop=[0,5000]; state.loop=yueLoop;
  $('cantoneseToggle').click();
  check('开启中文逐字粤拼，译文及英语音标保持原样', [...yueRow.querySelectorAll('rt')].map(n=>n.textContent).join('|')==='ngo5|coeng3|sɪŋ' && yueRow.querySelector('.lyric-translation').textContent==='原有译文');
  check('粤拼切换保持歌词行、循环和手动浏览位置', lyricRows[0]===yueRow && state.loop===yueLoop && state.resumeFollowAt===Infinity && state.scrollTarget===null);
  check('粤拼偏好写入且默认字段与罗马音独立', JSON.parse(localStorage.getItem('utatomo-display')).cantonese===true && !state.romaji);
  setDictionary(true); yueRow.querySelector('.token').click(); $('correctButton').click();
  $('correctReading').value='ngo4'; $('correctForm').dispatchEvent(new Event('submit',{cancelable:true}));
  check('粤拼修正提交独立系统标记并等待保存回执', actions.at(-1)[0]==='correct' && actions.at(-1)[1].readingSystem==='jyutping' && $('correctDialog').open && $('saveReading').disabled);
  onEvent('correctError',{message:'读音格式错误'});
  check('修正失败保留输入并允许重试', $('correctDialog').open && $('correctReading').value==='ngo4' && !$('saveReading').disabled && !$('correctError').hidden);
  const corrected={...yueLine,cantoneseTokens:yueTokens.map((t,i)=>i===0?{...t,reading:'ngo4',source:'本句用户校正'}:t)};
  onEvent('readingCorrected',{lines:[corrected],token:yueTokens[0]});
  check('保存仅更新词内读音，保留歌词行及循环浏览状态', !$('correctDialog').open && lyricRows[0]===yueRow && yueRow.querySelector('rt').textContent==='ngo4' && state.loop===yueLoop && state.resumeFollowAt===Infinity);
  setDictionary(false); state.loop=null; state.resumeFollowAt=0;
  const libraryData={tracks:[{key:'local:sample',source:'local',title:'本地练唱示例',artist:'原创',path:'C:/Music/sample.wav',duration:40000,favorite:false,available:true},
    {key:'cloud:123',source:'cloud',songId:'123',title:'粤语练唱示例',artist:'示例歌手',album:'原创示例',duration:80000,favorite:true,available:true},
    {key:'local:missing',source:'local',title:'移动过的音频',artist:'本地',path:'C:/Missing/song.wav',duration:0,favorite:true,available:false}],
    playlists:[{id:'practice',name:'每天一首',count:2}],total:3,page:0,pageSize:50,recentCounts:{local:2,cloud:1},current:{key:'cloud:123',favorite:true},options:{view:'recent',source:'all',query:'',page:0}};
  onEvent('library',libraryData); $('recentButton').click(); onEvent('library',libraryData); await wait(50);
  check('最近播放入口同时展示两种来源并提供切歌', $('libraryDialog').open && $('libraryTracks').children.length===3 && $('recentCount').textContent==='3');
  $('libraryTracks').querySelector('.track-play').click();
  check('最近播放切歌使用播放动作而非歌词替换', actions.at(-1)[0]==='libraryPlay' && actions.at(-1)[1].key==='local:sample');
  document.querySelector('[data-source="cloud"]').click();
  check('来源筛选发送云端来源条件', actions.at(-1)[0]==='libraryQuery' && actions.at(-1)[1].source==='cloud');
  $('librarySearchInput').value='晨光'; $('librarySearchInput').dispatchEvent(new Event('input')); await wait(180);
  check('列表支持输入搜索并回到第一页', actions.at(-1)[1].query==='晨光' && actions.at(-1)[1].page===0);
  onEvent('library',{...libraryData,tracks:[],total:0,options:{view:'recent',source:'cloud',query:'晨光',page:0}});
  check('无搜索结果提供清空搜索操作', $('libraryTracks').textContent.includes('清空搜索'));
  $('favoritesTab').click(); onEvent('library',{...libraryData,options:{view:'favorites',source:'all',query:'',page:0}});
  check('收藏支持本地添加、网易云添加和新建歌单', !$('playlistSidebar').hidden && !$('importLibraryAudio').hidden && !$('addCloudTrack').hidden && $('createPlaylist').getBoundingClientRect().height>0);
  $('createPlaylist').click(); $('playlistNameInput').value='夜间练唱'; $('playlistNameForm').dispatchEvent(new Event('submit',{cancelable:true}));
  check('新建歌单等待事务回执', actions.at(-1)[0]==='libraryCreatePlaylist' && $('playlistNameDialog').open && $('savePlaylistName').disabled);
  onEvent('libraryError',{message:'已有同名歌单',operation:'libraryCreatePlaylist'});
  check('重名歌单保留名称和错误', $('playlistNameDialog').open && !$('playlistNameError').hidden && !$('savePlaylistName').disabled);
  $('playlistNameDialog').close();
  $('libraryTracks').querySelector('[data-track-action="playlist"]').click();
  $('playlistPickerList').querySelector('button').click();
  check('最近曲目可加入本地歌单', actions.at(-1)[0]==='libraryMembership' && actions.at(-1)[1].playlistId==='practice');
  onEvent('librarySaved',{operation:'libraryMembership'});
  check('歌单保存成功才关闭选择器', !$('playlistPickerDialog').open);
  const missing=[...$('libraryTracks').children].find(r=>r.dataset.trackKey==='local:missing');
  check('缺失文件不可假装播放并提供重新定位', missing.querySelector('.track-play').disabled && missing.textContent.includes('重新定位'));
  $('libraryTracks').querySelector('[data-track-action="remove"]').click();
  check('移除曲库前明确说明保留音频', $('libraryConfirmDialog').open && $('libraryConfirmDescription').textContent.includes('不删除音频'));
  $('libraryConfirmDialog').close();
  check('最小窗口曲库内容没有横向溢出', $('libraryDialog').scrollWidth<=$('libraryDialog').clientWidth && $('libraryBody').scrollWidth<=$('libraryBody').clientWidth);
  window.__uiCapture='library'; await wait(220); window.__uiCapture=null;
  $('libraryDialog').close(); $('toolsDialog').showModal();
  window.__uiCapture='settings'; await wait(220); window.__uiCapture=null;
  $('toolsDialog').close(); await wait(80);
  // 同版本修订：字体切换只改样式，最爱和曲库/歌单是独立概念。
  const fontRow=lyricRows[0], fontBase=fontRow.querySelector('.token-base');
  const fontLoop=state.loop, readingNode=fontRow.querySelector('rt');
  onEvent('lyricFonts',{families:['Microsoft YaHei','Segoe UI','Microsoft YaHei','@Vertical']});
  check('字体下拉来自本机事件并去重排除竖排族', $('lyricFont').options.length===3 && !$('lyricFont').querySelector('option[value="@Vertical"]'));
  $('lyricFont').value='Segoe UI'; $('lyricFont').dispatchEvent(new Event('change'));
  check('选择字体即时生效并保存', getComputedStyle(fontBase).fontFamily.startsWith('"Segoe UI"') && JSON.parse(localStorage.getItem('utatomo-display')).lyricFont==='Segoe UI');
  check('字体切换保留行、注音、循环和常规字重', lyricRows[0]===fontRow && fontRow.querySelector('rt')===readingNode && state.loop===fontLoop && getComputedStyle(fontBase).fontWeight==='400');
  state.lyricFont='已卸载的字体'; onEvent('lyricFonts',{families:['Microsoft YaHei']});
  check('卸载的字体显示原因并回到默认', state.lyricFont==='' && $('lyricFontHint').textContent.includes('未安装') && getComputedStyle(fontBase).fontFamily.includes('Microsoft YaHei'));
  $('playlistCurrent').click();
  check('封面下当前歌可直接选择工具歌单', $('playlistPickerDialog').open && libraryUI.pickingCurrent);
  $('playlistPickerList').querySelector('button').click();
  check('当前歌加入歌单传递稳定身份而非红心', actions.at(-1)[0]==='libraryMembership' && actions.at(-1)[1].current===true && actions.at(-1)[1].key==='cloud:123');
  onEvent('librarySaved',{operation:'libraryMembership'});
  const heartStyle=getComputedStyle($('favoriteCurrent').querySelector('use'));
  check('已最爱红心实心深色且保留按下语义', heartStyle.fill===getComputedStyle($('favoriteCurrent')).color && $('favoriteCurrent').getAttribute('aria-pressed')==='true');
  $('libraryButton').click(); onEvent('library',{...libraryData,options:{view:'favorites',source:'all'}});
  $('lovedTracks').click();
  check('最爱是左侧固定分类并请求独立过滤', actions.at(-1)[1].view==='loved');
  onEvent('library',{...libraryData,tracks:[libraryData.tracks[1]],total:1,options:{view:'loved',source:'all'}});
  check('最爱视图不用全局移除混淆取消红心', $('libraryTitle').textContent==='最爱' && $('lovedTracks').getAttribute('aria-pressed')==='true' && !$('libraryTracks').querySelector('[data-track-action="remove"]') && !!$('libraryTracks').querySelector('[data-track-action="favorite"]'));
  onEvent('cloud',{connected:true,transport:'smtc'});
  check('普通同步模式提供显式后台切歌连接入口', !$('libraryConnectCloud').hidden);
  onEvent('cloud',{connected:true,transport:'client'});
  check('直连成功不重复显示连接入口', $('libraryConnectCloud').hidden);
  $('libraryDialog').close();
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
  window.__uiResult = {checks, errors: window.__errors, firstGeometry, modalEvidence, animationFramesPerSecond: Math.round(fps)};
})().catch(error => {window.__uiResult = {checks: [], errors: [String(error)]};});
