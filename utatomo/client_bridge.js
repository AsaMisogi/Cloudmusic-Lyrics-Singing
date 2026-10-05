/* 网易云 3.x 本机适配层。每次读取当前挂载的播放器组件，不保存旧歌曲的闭包。
 * 只提取播放信息；不枚举账户、凭据、历史记录。接口变化时返回不可用。
 * 使用客户端已有的 Redux 播放动作，让客户端处理跳转、缓冲和播放权限。
 */
(() => {
  function player() {
    const footer = document.querySelector('footer');
    const input = footer?.querySelector('input[type="range"]');
    if (!input) return null;
    const key = Object.keys(input).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    let fiber = input[key];
    let root = fiber;
    while (root?.return) root = root.return;
    if (root?.stateNode?.current && root.stateNode.current !== root && fiber?.alternate) fiber = fiber.alternate;
    for (let depth = 0; fiber && depth < 24; depth++, fiber = fiber.return) {
      // metadata 与进度同一次快照返回；Python 端以歌曲 ID 隔离切歌。
      const props = fiber.memoizedProps;
      if (props?.curTrack && typeof props.dispatch === 'function') return {input, props, footer};
    }
    return null;
  }
  function snapshot() {
    const p = player();
    if (!p) return null;
    const track = p.props.curTrack;
    const button = p.footer.querySelector('[data-testid="tid_playbar_play_btn"]');
    const icon = button?.querySelector('[role="img"]')?.getAttribute('aria-label');
    const duration = Number(p.input.max) * 1000;
    const position = Number(p.input.value) * 1000;
    if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(position)) return null;
    return {connected: true, songId: String(track.id), title: track.name,
      artist: (track.artists || track.ar || []).map(a => a.name).join(' / '),
      album: (track.album || track.al || {}).name || '',
      identity: String(track.id), position, duration, playing: icon === 'pause',
      canSeek: !p.input.disabled, canPlay: !!button, canRate: false,
      hasTimeline: true, rate: 1, transport: 'client',
      localAudio: p.props.curPlaying?.playFile || ''};
  }
  async function command(name, value, expectedId) {
    const p = player(), state = snapshot();
    if (!p || !state || (expectedId && state.songId !== expectedId)) throw Error('歌曲已切换，请重试操作。');
    if (name === 'seek' || name === 'seekAndPlay') {
      if (!state.canSeek || !Number.isFinite(value)) throw Error('当前歌曲不可跳转。');
      await p.props.dispatch({type: 'playing/setPlayingPosition', payload: {duration: Math.max(0, Math.min(state.duration, value)) / 1000}});
      // 等待定位成功，再重新检查当前歌与播放状态；不能用 toggle 猜测是否需要播放。
      if (name === 'seekAndPlay') {
        const latest = snapshot();
        if (!latest || latest.songId !== state.songId) throw Error('歌曲已切换，请重试操作。');
        if (!latest.playing) player().footer.querySelector('[data-testid="tid_playbar_play_btn"]').click();
      }
    } else if (name === 'toggle' || name === 'pause') {
      if (name === 'toggle' || state.playing) p.footer.querySelector('[data-testid="tid_playbar_play_btn"]').click();
    } else throw Error('客户端暂不支持此操作。');
    return true;
  }
  window.__utatomoClient = {snapshot, command};
  return snapshot();
})()
