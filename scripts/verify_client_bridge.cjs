/* 用固定的播放器组件验证正式适配脚本；不连接或操作用户的网易云。
 * 重点检查按 ID 切歌只派发播放动作，不走启动协议或窗口激活动作。
 */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const actions = [];
const props = {curTrack:{id:'123',name:'示例',artists:[]},dispatch:async action=>actions.push(action)};
const input = {max:'240',value:'10',disabled:false,__reactFiber_fixture:{memoizedProps:props}};
const button = {querySelector:()=>({getAttribute:()=> 'pause'}),click:()=>actions.push('toggle')};
const footer = {querySelector:selector=>selector==='input[type="range"]' ? input : button};
const context = {window:{},document:{querySelector:()=>footer}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('utatomo/client_bridge.js','utf8'), context);
(async()=>{
  const api=context.window.__utatomoClient;
  assert.equal(await api.command('playSong','456'),true);
  assert.deepEqual(JSON.parse(JSON.stringify(actions)), [{type:'async:action/onWebMessage',payload:{message:{cmd:'play',type:'song',id:'456'}}}]);
  assert.equal(api.snapshot().songId,'123'); // 派发不篡改快照，等待客户端实际切歌。
  await assert.rejects(api.command('playSong','1; arbitrary'));
  assert.equal(actions.length,1);
  await assert.rejects(api.command('seek',5000,'stale'));
  assert.equal(actions.length,1);
  await api.command('seek',5000,'123');
  assert.equal(actions[1].type,'playing/setPlayingPosition');
  assert.equal(actions[1].payload.duration,5);
  console.log('后台播放消息、真实快照、非法 ID、旧歌隔离及既有定位接口：全部通过。');
})().catch(error=>{console.error(error); process.exitCode=1;});
