// 设置由原生端确认后回显；托盘菜单的修改也走同一事件，不维护两套开关状态。
let desktopPrefs={}, segmentGeneration=0;
function drawSegments(row,line){
  const text=line.segments?.[state.romaji?'roman':'kana'];
  let strip=row.querySelector('.segment-strip');
  row.classList.toggle('manual-reading',!!text);
  if(!text){strip?.remove();return;}
  if(!strip){strip=document.createElement('div');strip.className='segment-strip';row.prepend(strip);}
  // 保持读音可复制，额外的呼吸间距交给样式，不把空格写回练唱稿。
  strip.replaceChildren();
  text.split('/').forEach((part,i)=>{
    if(i){const mark=document.createElement('span');mark.className='reading-cut';mark.textContent=' / ';strip.append(mark);}
    strip.append(part.trim());
  });
}
function practiceEvent(kind,data){
  if(kind==='desktop'){
    desktopPrefs=data;
    showAlignment(data.align||'center');
    const box=$('deskSwatch');
    box.style.backgroundColor=data.paper+Math.round(255*data.opacity/100).toString(16).padStart(2,'0');
    box.classList.toggle('has-shadow',!!data.shadow);
    box.style.fontSize=data.size+'px';
    $('previewInk').style.color=data.ink;$('previewInk').firstElementChild.style.color=data.highlight;
    $('previewNote').style.color=data.note;$('previewTrans').style.color=data.trans;
    // 有原文时逐组上标；只选注音时保留独立读音，预览与浮窗使用相同的层次。
    $('previewNote').textContent=data.roman?'asa no hikari':'あさ の ひかり';
    const notes=$('previewInk').querySelectorAll('rt');
    notes.forEach((el,i)=>{el.textContent=(data.roman?['asa','hikari']:['あさ','ひかり'])[i];el.style.color=data.note;el.hidden=!data.reading;});
    $('previewInk').hidden=!data.original;$('previewNote').hidden=!data.reading||data.original;$('previewTrans').hidden=!data.translation;
    for(const el of document.querySelectorAll('[data-desk]')){
      const v=data[el.dataset.desk]; if(el.type==='checkbox')el.checked=v;else el.value=v;
    }
    $('desktopQuick').setAttribute('aria-pressed',String(data.enabled));$('deskSize').textContent=data.size+' px';$('deskOpacity').textContent=data.opacity+'%';
  }else if(kind==='backupNotice' || (kind==='error' && ['backupImport','backupExport'].includes(data.operation))){
    $('backupFeedback').textContent=data.message;
  }else if(kind==='restoreDisplay'){
    localStorage.setItem('utatomo-display',JSON.stringify(data));
    // 等后端清除一次性恢复标记再刷新，避免重复恢复或重复连接。
    backend.action('displayRestored','null',()=>location.reload());
  }else if(kind==='pasteAccepted'){
    $('pasteDialog').close();$('toolsDialog').close();$('pasteText').value='';
  }else if(kind==='segmentEditor'){
    segmentGeneration=data.generation;
    $('segmentLine').replaceChildren(...state.lines.map((l,i)=>new Option(`${i+1}. ${l.text}`,i)));
    $('segmentLine').value=data.index??Math.max(0,state.active);fillSegment();$('segmentDialog').showModal();
  }else if(kind==='segmentsSaved'){
    if(state.lines[data.index]){
      const row=lyricRows[data.index],line=data.line;
      state.lines[data.index]=line;
      const original=row.querySelector('.lyric-original');
      original.replaceChildren();appendLineTokens(original,line);drawSegments(row,line);
      row.setAttribute('aria-label',line.text);
      activeTokens=Array.from(lyricRows[state.active]?.querySelectorAll('.token-base')||[]);
      updateHighlight(estimatedPosition());
    }
    $('segmentForm').querySelector('.primary-button').disabled=false;
    $('segmentDialog').close();toast('分段已保存');
  }else if(kind==='error' && ['pasteLyrics','saveSegments'].includes(data.operation)){
    $('segmentForm').querySelector('.primary-button').disabled=false;
    $(data.operation==='pasteLyrics'?'pasteError':'segmentError').textContent=data.message;
  }else return false;
  return true;
}
let cutField=$('segmentOriginal'),autoReadings={},resetReadings=false;
function fillSegment(){
  const line=state.lines[Number($('segmentLine').value)];if(!line)return;
  cutField=$('segmentOriginal');resetReadings=false;
  cutField.value=line.segments?.original||line.text;
  for(const [id,key] of [['segmentKana','kana'],['segmentRoman','roman']]){
    const el=$(id);
    autoReadings[key]=displayTokens(line).map(t=>(key==='roman' && t.romaji)||t.reading||t.text).join('');
    el.value=line.segments?.[key]||autoReadings[key];
  }
  $('segmentError').textContent='';
  $('segmentForm').querySelector('.primary-button').disabled=false;
}
for(const el of document.querySelectorAll('#segmentForm input'))el.onfocus=()=>cutField=el;
$('insertCut').onclick=()=>{
  const pos=cutField.selectionStart;
  if(pos===0||pos===cutField.value.length||cutField.value.slice(pos-1,pos+1).includes('/')){
    $('segmentError').textContent='请把光标放在两个音节或文字之间。';cutField.focus();return;
  }
  cutField.setRangeText('/',pos,pos,'end');cutField.focus();$('segmentError').textContent='';
};
$('resetSentence').onclick=()=>{
  const line=state.lines[Number($('segmentLine').value)];
  $('segmentOriginal').value=line.editSource?.text??line.text;
  $('segmentKana').value=$('segmentRoman').value='';resetReadings=true;
  $('segmentError').textContent='保存后恢复原文和自动注音。';
};
for(const button of document.querySelectorAll('[data-pref]'))button.onclick=()=>{
  for(const tab of document.querySelectorAll('[data-pref]')){
    const current=tab===button;tab.setAttribute('aria-pressed',String(current));$('pref-'+tab.dataset.pref).hidden=!current;
  }
  document.querySelector('.pref-body').scrollTop=0;
};
$('desktopQuick').onclick=()=>action('desktopOption',['enabled',!desktopPrefs.enabled]);
for(const el of document.querySelectorAll('[data-desk]'))el.onchange=()=>action('desktopOption',[el.dataset.desk,el.type==='checkbox'?el.checked:el.type==='range'?Number(el.value):el.value]);
$('backupExport').onclick=()=>action('backupExport',JSON.parse(localStorage.getItem('utatomo-display')||'{}'));
$('backupImport').onclick=()=>action('backupImport');
$('pasteOpen').onclick=()=>{$('pasteError').textContent='';$('pasteDialog').showModal();$('pasteText').focus();};
$('pasteForm').onsubmit=e=>{e.preventDefault();action('pasteLyrics',$('pasteText').value);};
$('segmentsOpen').onclick=()=>{if(state.lines.length)action('editSegments');else toast('请先导入或播放有歌词的歌曲。',true);};
$('segmentLine').onchange=fillSegment;
$('segmentForm').onsubmit=e=>{
  e.preventDefault();
  const idx=Number($('segmentLine').value),line=state.lines[idx];
  if(!line)return;
  const fields={original:$('segmentOriginal').value};
  // 自动填入的读音不算手动修正，否则日后改字或修正词典读音时会被旧文本覆盖。
  for(const [id,key] of [['segmentKana','kana'],['segmentRoman','roman']]){
    const v=$(id).value;
    fields[key]=!resetReadings && !line.segments?.[key] && v===autoReadings[key]?'':v;
  }
  $('segmentForm').querySelector('.primary-button').disabled=true;
  action('saveSegments',{index:idx,generation:segmentGeneration,...fields});
};

// 同一设置驱动主谱面与原生浮窗。水平对齐不改变纵向跟随模式，也不重置播放时钟。
const alignmentNames={center:'居中',left:'居左',right:'居右'};
function showAlignment(value){
  document.body.dataset.align=value;
  $('alignment').querySelector('span').textContent=alignmentNames[value];
  $('alignment').setAttribute('aria-label','歌词'+alignmentNames[value]+'，点击切换');
}
$('alignment').onclick=()=>{
  const keys=Object.keys(alignmentNames);
  const next=keys[(keys.indexOf(document.body.dataset.align||'center')+1)%keys.length];
  action('desktopOption',['align',next]);
};

$('importPopover').addEventListener('click',()=>{$('importPopover').hidePopover();});
$('importMenu').onclick=()=>{
  const r=$('importMenu').getBoundingClientRect();
  Object.assign($('importPopover').style,{top:r.bottom+5+'px',left:Math.min(r.left,innerWidth-210)+'px'});
};
