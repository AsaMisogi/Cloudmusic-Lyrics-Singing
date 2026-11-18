/* 一套主题总有两个独立色板。只保存用户选择与自定义基色，边框、次级文字
   和交互状态由同一组语义色推导。换主题不重建歌词、暂停播放或变更桌面字幕的专属配色。 */
const Theme = (() => {
  const sets = {
    studio: {name:'紫灰',dark:['#17181d','#f3f1f8','#c4afff'],light:['#f7f6fa','#272534','#645092']},
    tide:   {name:'海雾',dark:['#141c23','#edf4fa','#92cef0'],light:['#f3f7fa','#21313d','#28658a']},
    amber:  {name:'琥珀',dark:['#201d1b','#f7f1e8','#efbd81'],light:['#faf6ef','#332d25','#92551c']}
  };
  const keys=['bg','text','accent'];
  let id='studio',mode='dark',custom={dark:[...sets.studio.dark],light:[...sets.studio.light]};
  const el=id=>document.getElementById(id);
  const valid=a=>Array.isArray(a)&&a.length===3&&a.every(x=>/^#[a-f\d]{6}$/i.test(x));
  const palette=()=>id==='custom'?custom[mode]:sets[id][mode];
  const rgb=hex=>[1,3,5].map(n=>parseInt(hex.slice(n,n+2),16));
  const luminance=c=>rgb(c).map(n=>n/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((a,n,i)=>a+n*[.2126,.7152,.0722][i],0);
  const contrast=(a,b)=>{let x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  function mix(a,b,t){
    const end=rgb(b);return '#'+rgb(a).map((n,i)=>Math.round(n+(end[i]-n)*t).toString(16).padStart(2,'0')).join('');
  }
  function render(){
    const [paper,ink,accent]=palette(),root=document.documentElement,light=mode==='light';
    root.style.colorScheme=mode;root.dataset.scheme=mode;
    const tones={
      paper,ink,green:accent,sun:accent,sidebar:mix(paper,light?ink:'#000000',light ? .045 : .26),
      panel:mix(paper,light?'#ffffff':ink,light ? .80 : .045),surface:mix(paper,ink,.055),
      control:mix(paper,ink,.085),hover:mix(paper,ink,.11),active:mix(paper,accent,.14),
      muted:mix(ink,paper,.26),quiet:mix(ink,paper,.42),line:mix(paper,ink,.14),
      'strong-line':mix(paper,ink,.24),'fill-track':mix(paper,ink,.24),
      'on-accent':contrast('#17161b',accent)>contrast('#ffffff',accent)?'#17161b':'#ffffff',
      danger:light?'#a13732':'#ffb2aa', warning:light?'#885516':'#f1cd93'
    };
    for(const [k,v] of Object.entries(tones))root.style.setProperty('--'+k,v);
    el('themePreset').value=id;
    for(const b of document.querySelectorAll('[data-scheme-choice]'))b.setAttribute('aria-pressed',String(b.dataset.schemeChoice===mode));
    keys.forEach((key,i)=>el('theme-'+key).value=palette()[i]);
    el('themeSample').textContent=(id==='custom'?'自定义':sets[id].name)+' · '+(light?'亮色':'深色');
    el('themeContrast').textContent=Math.min(contrast(ink,paper),contrast(accent,paper))<4.5?'文字或已唱色与背景接近，可调深或调浅以方便跟唱。':'';
  }
  // 网页先恢复本地配色，WebChannel 稍后才就绪：握手时同步一次，之后只在实际改色时通知原生窗口。
  function syncFrame(){
    const [background,text]=palette();
    window.backend?.setFrameTheme?.(mode==='dark',background,text);
  }
  function commit(){render();syncFrame();savePreferences();}
  function restore(value){
    id=value?.id==='custom'||Object.hasOwn(sets,value?.id)?value.id:'studio';
    mode=value?.mode==='light'?'light':'dark';
    for(const m of ['light','dark'])custom[m]=valid(value?.custom?.[m])?[...value.custom[m]]:[...sets.studio[m]];
    render();
  }
  function bind(){
    el('themePreset').onchange=e=>{id=e.target.value;commit();};
    for(const b of document.querySelectorAll('[data-scheme-choice]'))b.onclick=()=>{mode=b.dataset.schemeChoice;commit();};
    for(const [i,key] of keys.entries())el('theme-'+key).oninput=e=>{
      // 第一次调色复制所选预设的亮暗整对；之后修改当前外观不覆盖另一套。
      if(id!=='custom'){custom={dark:[...sets[id].dark],light:[...sets[id].light]};id='custom';}
      custom[mode][i]=e.target.value;commit();
    };
    el('themeReset').onclick=()=>{custom[mode]=[...sets.studio[mode]];id='custom';commit();};
  }
  bind();return {restore,syncFrame,snapshot:()=>({id,mode,custom})};
})();

