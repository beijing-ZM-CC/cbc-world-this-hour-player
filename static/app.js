(() => {
  const FEED_GROUP_LABELS = {
    twth: "The World This Hour（每小时新闻 · 自动归档）",
    wr: "World Report（每日晨间新闻 · 10分钟）",
    ywt: "Your World Tonight（每日晚间新闻 · 30分钟）",
  };
  const SPEEDS = [1.0, 1.25, 1.5, 0.75];

  const PLAY_MODE_ORDER = ["sequential", "loop_para", "repeat_one", "shuffle"];
  const PLAY_MODE_META = {
    sequential: { label: "顺次播放", tip: "当前：顺次播放（播完自动播放下一期）" },
    loop_para: { label: "本段循环", tip: "当前：本段循环（反复循环播放当前段落）" },
    repeat_one: { label: "单曲循环", tip: "当前：单曲循环（播完重复播放本期）" },
    shuffle: { label: "随机播放", tip: "当前：随机播放（播完随机切换下一期）" },
  };

  const FONT_SIZE_ORDER = ["normal", "medium", "large"];
  const FONT_SIZE_LABELS = {
    normal: "字号:正常",
    medium: "字号:中",
    large: "字号:大",
  };

  const appShell = document.getElementById("app-shell");
  const geminiBadge = document.getElementById("gemini-badge");
  const easterOverlay = document.getElementById("easter-overlay");
  const easterImg = document.getElementById("easter-img");
  const audio = document.getElementById("audio-player");
  const episodeSelect = document.getElementById("episode-select");
  const episodeIndexBadge = document.getElementById("episode-index-badge");

  const btnPrevPara = document.getElementById("btn-prev-para");
  const btnPlay = document.getElementById("btn-play");
  const iconPlay = document.getElementById("icon-play");
  const iconPause = document.getElementById("icon-pause");
  const labelPlay = document.getElementById("label-play");
  const btnNextPara = document.getElementById("btn-next-para");

  const btnPlayMode = document.getElementById("btn-play-mode");
  const iconModeSequential = document.getElementById("icon-mode-sequential");
  const iconModeLoopPara = document.getElementById("icon-mode-loop-para");
  const iconModeRepeat = document.getElementById("icon-mode-repeat");
  const iconModeShuffle = document.getElementById("icon-mode-shuffle");
  const labelPlayMode = document.getElementById("label-play-mode");

  const btnScrollMode = document.getElementById("btn-scroll-mode");
  const iconScrollLock = document.getElementById("icon-scroll-lock");
  const iconScrollFree = document.getElementById("icon-scroll-free");
  const labelScrollMode = document.getElementById("label-scroll-mode");

  const btnFontSize = document.getElementById("btn-font-size");
  const labelFontSize = document.getElementById("label-font-size");

  const btnDockPos = document.getElementById("btn-dock-pos");
  const labelDockPos = document.getElementById("label-dock-pos");

  const btnSpeed = document.getElementById("btn-speed");
  const btnMute = document.getElementById("btn-mute");
  const iconVol = document.getElementById("icon-vol");
  const iconMuted = document.getElementById("icon-muted");
  const volumeSlider = document.getElementById("volume-slider");
  const btnLayout = document.getElementById("btn-layout");
  const labelLayout = document.getElementById("label-layout");
  const btnSave = document.getElementById("btn-save");
  const saveDropdown = document.getElementById("save-dropdown");
  const btnSync = document.getElementById("btn-sync");
  const iconSync = document.getElementById("icon-sync");
  const labelSync = document.getElementById("label-sync");
  const btnInstall = document.getElementById("btn-install");
  const btnTheme = document.getElementById("btn-theme");
  const themeIcon = document.getElementById("theme-icon");

  const progressHit = document.getElementById("progress-hit");
  const progressBuffer = document.getElementById("progress-buffer");
  const progressFill = document.getElementById("progress-fill");
  const progressThumb = document.getElementById("progress-thumb");
  const timeCurrent = document.getElementById("time-current");
  const timeDuration = document.getElementById("time-duration");
  const hoverPreview = document.getElementById("hover-preview");
  const episodeMetaHint = document.getElementById("episode-meta-hint");

  const subtitlesMain = document.getElementById("subtitles-main");
  const panelSplit = document.getElementById("panel-split");
  const panelStack = document.getElementById("panel-stack");
  const counterEn = document.getElementById("counter-en");
  const counterZh = document.getElementById("counter-zh");
  const counterStack = document.getElementById("counter-stack");
  const toastEl = document.getElementById("toast");

  let appMode = "api";
  let episodes = [];
  let currentEpisode = null;
  let subtitles = [];
  let paragraphs = [];
  let sentenceToPara = [];
  let splitEnSpans = [];
  let splitZhSpans = [];
  let stackEnSpans = [];
  let stackZhSpans = [];
  let splitRowEls = [];
  let stackCardEls = [];
  let activeIndex = -1;
  let activeParaIndex = -1;
  let loopParaIndex = 0;

  let speedIdx = 0;
  let isDragging = false;
  let pollTimer = null;
  let toastTimer = null;
  let deferredInstallPrompt = null;
  let pendingAutoPlay = false;
  let geminiClicks = 0;
  let easterTimer = null;

  // 双子座图标彩蛋：点击第 10 次出现表情包 1，再点击 10 次（第 20 次）出现表情包 2，之后每 10 次交替出现
  const EASTER_STICKERS = ["./icons/easter-1.png", "./icons/easter-2.png"];

  function hideEasterEgg() {
    clearTimeout(easterTimer);
    easterOverlay.classList.remove("show");
    easterOverlay.setAttribute("aria-hidden", "true");
  }

  function showEasterEgg(stickerIdx) {
    clearTimeout(easterTimer);
    easterImg.src = EASTER_STICKERS[stickerIdx];
    easterOverlay.classList.add("show");
    easterOverlay.setAttribute("aria-hidden", "false");
    easterTimer = setTimeout(hideEasterEgg, 3600);
  }

  geminiBadge.addEventListener("click", () => {
    geminiClicks += 1;
    if (geminiClicks % 10 === 0) {
      const stage = (Math.floor(geminiClicks / 10) - 1) % EASTER_STICKERS.length;
      showEasterEgg(stage);
    }
  });

  easterOverlay.addEventListener("click", hideEasterEgg);

  const savedPlayMode = localStorage.getItem("cbc_player_play_mode");
  let playMode = PLAY_MODE_ORDER.includes(savedPlayMode) ? savedPlayMode : "sequential";
  const shuffleHistory = new Set();

  // 滚动模式：'sync'（同步滚动，锁定手工滑动）| 'free'（自由滚动，不随音频滚动，可自由滑动与点选）
  const savedScrollMode = localStorage.getItem("cbc_player_scroll_mode");
  let scrollMode = savedScrollMode === "free" ? "free" : "sync";

  // 字号：'normal' | 'medium' | 'large'
  const savedFontSize = localStorage.getItem("cbc_player_font_size");
  let fontSize = FONT_SIZE_ORDER.includes(savedFontSize) ? savedFontSize : "normal";

  // 按钮位置：'top' | 'bottom'
  const savedDockPos = localStorage.getItem("cbc_player_dock_pos");
  let dockPos = savedDockPos === "bottom" ? "bottom" : "top";

  // 视图布局：桌面与手机均可自由切换左右分栏 / 双语交错
  let layoutMode = localStorage.getItem("cbc_player_layout") || "split";

  function showToast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2500);
  }

  function formatTime(sec) {
    if (!Number.isFinite(sec) || sec < 0) return "00:00";
    const total = Math.floor(sec);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) {
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function formatSrtTs(sec) {
    const msTotal = Math.max(0, Math.round((sec || 0) * 1000));
    const h = Math.floor(msTotal / 3600000);
    const m = Math.floor((msTotal % 3600000) / 60000);
    const s = Math.floor((msTotal % 60000) / 1000);
    const ms = msTotal % 1000;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
  }

  function effectiveDuration() {
    if (Number.isFinite(audio.duration) && audio.duration > 0) return audio.duration;
    return currentEpisode?.duration || 0;
  }

  function safeSlug(ep) {
    const raw = `CBC_${ep?.feed_name || "news"}_${ep?.pub_display || ep?.id || "episode"}`;
    return raw.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 90) || "cbc_episode";
  }

  // 注册 Service Worker & Android 安装引导
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    });
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    btnInstall.classList.remove("hidden");
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    btnInstall.classList.add("hidden");
    showToast("已安装「双子座」到手机桌面");
  });

  btnInstall.addEventListener("click", async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice.catch(() => {});
    deferredInstallPrompt = null;
    btnInstall.classList.add("hidden");
  });

  // 1. 滚动模式切换：同步滚动（锁定手工滑动） ↔ 自由滚动（不随音频滚动，可自由滑动与点选）
  function applyScrollMode(mode, notify = false) {
    scrollMode = mode === "free" ? "free" : "sync";
    localStorage.setItem("cbc_player_scroll_mode", scrollMode);
    const isSync = scrollMode === "sync";

    btnScrollMode.classList.toggle("active-sync", isSync);
    btnScrollMode.dataset.scrollMode = scrollMode;
    iconScrollLock.style.display = isSync ? "block" : "none";
    iconScrollFree.style.display = isSync ? "none" : "block";
    labelScrollMode.textContent = isSync ? "同步滚动" : "自由滚动";
    btnScrollMode.title = isSync
      ? "同步滚动中：字幕随音频自动滚动，手工滑动已锁定；点击切换为自由滚动"
      : "自由滚动中：字幕不随音频滚动，可自由滑动并点选跳转；点击切换回同步滚动";

    panelSplit.classList.toggle("scroll-locked", isSync);
    panelStack.classList.toggle("scroll-locked", isSync);

    if (isSync && activeIndex >= 0) {
      requestAnimationFrame(() => scrollPanelsTo(activeIndex, true));
    }
    if (notify) {
      showToast(isSync ? "已开启：同步滚动（手工滑动已锁定）" : "已切换：自由滚动（可手动滑动并点选跳转）");
    }
  }
  applyScrollMode(scrollMode, false);

  btnScrollMode.addEventListener("click", () => {
    applyScrollMode(scrollMode === "sync" ? "free" : "sync", true);
  });

  // 同步滚动开启时严格屏蔽手工滚轮与触摸滑动
  function blockManualScrollIfSynced(e) {
    if (scrollMode === "sync") {
      e.preventDefault();
    }
  }
  [panelSplit, panelStack].forEach((p) => {
    p.addEventListener("wheel", blockManualScrollIfSynced, { passive: false });
    p.addEventListener("touchmove", blockManualScrollIfSynced, { passive: false });
  });

  // 2. 字号三档调节（正常 / 中 / 大）
  function applyFontSize(size, notify = false) {
    fontSize = FONT_SIZE_ORDER.includes(size) ? size : "normal";
    localStorage.setItem("cbc_player_font_size", fontSize);
    document.documentElement.setAttribute("data-font-size", fontSize);
    labelFontSize.textContent = FONT_SIZE_LABELS[fontSize];
    btnFontSize.dataset.fontSize = fontSize;
    if (scrollMode === "sync" && activeIndex >= 0) {
      requestAnimationFrame(() => scrollPanelsTo(activeIndex, false));
    }
    if (notify) showToast(`字幕${FONT_SIZE_LABELS[fontSize]}`);
  }
  applyFontSize(fontSize, false);

  btnFontSize.addEventListener("click", () => {
    const nextIdx = (FONT_SIZE_ORDER.indexOf(fontSize) + 1) % FONT_SIZE_ORDER.length;
    applyFontSize(FONT_SIZE_ORDER[nextIdx], true);
  });

  // 3. 底部按钮 / 顶部按钮整体位置切换（节目标题栏始终固定在最上方）
  function applyDockPos(pos, notify = false) {
    dockPos = pos === "bottom" ? "bottom" : "top";
    localStorage.setItem("cbc_player_dock_pos", dockPos);
    const isBottom = dockPos === "bottom";
    appShell.classList.toggle("controls-bottom", isBottom);
    labelDockPos.textContent = isBottom ? "按钮顶部" : "按钮底部";
    btnDockPos.dataset.dock = dockPos;
    btnDockPos.title = isBottom ? "点击将操作按钮移回屏幕上方" : "点击将操作按钮整体移至屏幕下方";
    if (scrollMode === "sync" && activeIndex >= 0) {
      requestAnimationFrame(() => scrollPanelsTo(activeIndex, false));
    }
    if (notify) showToast(isBottom ? "操作按钮已移至屏幕下方" : "操作按钮已切换回屏幕上方");
  }
  applyDockPos(dockPos, false);

  btnDockPos.addEventListener("click", () => {
    applyDockPos(dockPos === "top" ? "bottom" : "top", true);
  });

  // 4. 播放模式四态切换（顺次播放 / 本段循环 / 单曲循环 / 随机播放）
  function applyPlayMode(mode, notify = false) {
    playMode = PLAY_MODE_ORDER.includes(mode) ? mode : "sequential";
    localStorage.setItem("cbc_player_play_mode", playMode);
    if (playMode === "loop_para") {
      loopParaIndex = activeParaIndex >= 0 ? activeParaIndex : 0;
    }
    const meta = PLAY_MODE_META[playMode];
    labelPlayMode.textContent = meta.label;
    btnPlayMode.title = `${meta.tip}，点击切换`;
    btnPlayMode.dataset.mode = playMode;

    iconModeSequential.style.display = playMode === "sequential" ? "block" : "none";
    iconModeLoopPara.style.display = playMode === "loop_para" ? "block" : "none";
    iconModeRepeat.style.display = playMode === "repeat_one" ? "block" : "none";
    iconModeShuffle.style.display = playMode === "shuffle" ? "block" : "none";

    if (notify) {
      const extra = (playMode === "loop_para" && paragraphs.length > 0) ? `（第 ${loopParaIndex + 1} 段）` : "";
      showToast(`已切换为：${meta.label}${extra}`);
    }
  }
  applyPlayMode(playMode, false);

  btnPlayMode.addEventListener("click", () => {
    const nextIdx = (PLAY_MODE_ORDER.indexOf(playMode) + 1) % PLAY_MODE_ORDER.length;
    applyPlayMode(PLAY_MODE_ORDER[nextIdx], true);
  });

  // 5. 前一段 / 后一段跳转
  function jumpToParagraph(delta) {
    if (!paragraphs.length) {
      // 无字幕段落时回退为 ±10 秒跳转
      seekTo((audio.currentTime || 0) + delta * 10);
      return;
    }
    const basePara = activeParaIndex >= 0 ? activeParaIndex : 0;
    const targetPara = Math.max(0, Math.min(paragraphs.length - 1, basePara + delta));
    loopParaIndex = targetPara;
    const para = paragraphs[targetPara];
    seekTo(para.start + 0.04, true);
    showToast(`已跳转至第 ${targetPara + 1} / ${paragraphs.length} 段`);
  }

  btnPrevPara.addEventListener("click", () => jumpToParagraph(-1));
  btnNextPara.addEventListener("click", () => jumpToParagraph(1));

  // 本段循环精准检测（防止播过当前段尾）
  function checkParagraphLoop() {
    if (playMode !== "loop_para" || audio.paused || !paragraphs.length) return;
    const idx = Math.max(0, Math.min(paragraphs.length - 1, loopParaIndex));
    const para = paragraphs[idx];
    if (!para) return;
    if ((audio.currentTime || 0) >= para.end - 0.06) {
      audio.currentTime = Math.max(0, para.start + 0.02);
      updateProgressUI();
      syncSubtitleHighlight(true);
    }
  }
  setInterval(checkParagraphLoop, 150);

  // 布局模式切换（左右分栏 / 双语交错）
  function applyLayout(mode, savePref = false) {
    layoutMode = mode === "stack" ? "stack" : "split";
    subtitlesMain.classList.toggle("mode-stack", layoutMode === "stack");
    subtitlesMain.classList.toggle("mode-split", layoutMode === "split");
    labelLayout.textContent = layoutMode === "stack" ? "双语交错" : "左右分栏";
    if (savePref) localStorage.setItem("cbc_player_layout", layoutMode);
    if (scrollMode === "sync" && activeIndex >= 0) {
      requestAnimationFrame(() => scrollPanelsTo(activeIndex, false));
    }
  }
  applyLayout(layoutMode, false);
  btnLayout.addEventListener("click", () => {
    applyLayout(layoutMode === "stack" ? "split" : "stack", true);
  });

  // 主题切换
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    themeIcon.textContent = theme === "dark" ? "☀️" : "🌙";
    localStorage.setItem("cbc_player_theme", theme);
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute("content", theme === "dark" ? "#131a24" : "#d92626");
  }
  const savedTheme = localStorage.getItem("cbc_player_theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(savedTheme);
  btnTheme.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });

  // Android 锁屏 / 蓝牙耳机媒体控制（Media Session API）
  function updateMediaSessionMetadata() {
    if (!("mediaSession" in navigator) || !currentEpisode) return;
    try {
      const iconUrl = new URL("./icons/icon-512.png", window.location.href).href;
      navigator.mediaSession.metadata = new MediaMetadata({
        title: currentEpisode.display_title || currentEpisode.title || "The World This Hour",
        artist: `CBC Radio · ${currentEpisode.feed_name || "News"}`,
        album: "双子座 · CBC 双语字幕播放器",
        artwork: [{ src: iconUrl, sizes: "512x512", type: "image/png" }],
      });
    } catch (_) {}
  }

  function updateMediaSessionPosition() {
    if (!("mediaSession" in navigator) || !("setPositionState" in navigator.mediaSession)) return;
    const dur = effectiveDuration();
    if (!Number.isFinite(dur) || dur <= 0) return;
    try {
      navigator.mediaSession.setPositionState({
        duration: dur,
        playbackRate: audio.playbackRate || 1.0,
        position: Math.min(dur, Math.max(0, audio.currentTime || 0)),
      });
    } catch (_) {}
  }

  if ("mediaSession" in navigator) {
    try {
      navigator.mediaSession.setActionHandler("play", () => audio.play().catch(() => {}));
      navigator.mediaSession.setActionHandler("pause", () => audio.pause());
      navigator.mediaSession.setActionHandler("seekbackward", () => jumpToParagraph(-1));
      navigator.mediaSession.setActionHandler("seekforward", () => jumpToParagraph(1));
      navigator.mediaSession.setActionHandler("seekto", (d) => {
        if (typeof d.seekTime === "number") seekTo(d.seekTime, true);
      });
      navigator.mediaSession.setActionHandler("nexttrack", () => advanceEpisode(1, true));
      navigator.mediaSession.setActionHandler("previoustrack", () => advanceEpisode(-1, true));
    } catch (_) {}
  }

  function pickNextEpisodeIndex(direction = 1) {
    if (!episodes.length) return -1;
    const curIdx = episodes.findIndex((e) => e.id === currentEpisode?.id);
    if (episodes.length === 1) return 0;

    if (playMode === "shuffle") {
      if (currentEpisode?.id) shuffleHistory.add(currentEpisode.id);
      let candidates = episodes
        .map((ep, idx) => ({ ep, idx }))
        .filter(({ ep, idx }) => idx !== curIdx && !shuffleHistory.has(ep.id));
      if (!candidates.length) {
        shuffleHistory.clear();
        if (currentEpisode?.id) shuffleHistory.add(currentEpisode.id);
        candidates = episodes.map((ep, idx) => ({ ep, idx })).filter(({ idx }) => idx !== curIdx);
      }
      const chosen = candidates[Math.floor(Math.random() * candidates.length)];
      return chosen ? chosen.idx : 0;
    }

    const base = curIdx >= 0 ? curIdx : 0;
    return (base + direction + episodes.length) % episodes.length;
  }

  function advanceEpisode(direction = 1, fromManual = false) {
    if (!episodes.length) return;
    if (!fromManual && playMode === "loop_para" && paragraphs.length > 0) {
      const idx = Math.max(0, Math.min(paragraphs.length - 1, loopParaIndex));
      audio.currentTime = Math.max(0, paragraphs[idx].start + 0.02);
      syncSubtitleHighlight(true);
      audio.play().catch(() => {});
      return;
    }
    if (!fromManual && playMode === "repeat_one") {
      audio.currentTime = 0;
      syncSubtitleHighlight(true);
      audio.play().catch(() => {});
      return;
    }
    const targetIdx = pickNextEpisodeIndex(direction);
    if (targetIdx < 0) return;
    const targetEp = episodes[targetIdx];
    const modeTag = playMode === "shuffle" ? "随机播放" : "顺次播放";
    showToast(`${modeTag}：${targetEp.display_title}`);
    selectEpisode(targetEp.id, true);
  }

  // 字幕分段工具与本地保存导出
  function groupSubtitlesByParagraph(list) {
    const groups = [];
    list.forEach((item, idx) => {
      const pKey = typeof item.paragraph === "number" ? item.paragraph : idx;
      if (!groups.length || groups[groups.length - 1].key !== pKey) {
        groups.push({ key: pKey, index: groups.length, start: item.start, end: item.end, items: [{ idx, item }] });
      } else {
        const g = groups[groups.length - 1];
        g.end = item.end;
        g.items.push({ idx, item });
      }
    });
    return groups;
  }

  function buildSrtText(list, mode) {
    return list.map((item, i) => {
      const en = (item.en || "").trim();
      const zh = (item.zh || "").trim();
      const body = mode === "en" ? en : (mode === "zh" ? (zh || en) : (zh ? `${en}\n${zh}` : en));
      return `${i + 1}\n${formatSrtTs(item.start)} --> ${formatSrtTs(item.end)}\n${body}\n`;
    }).join("\n");
  }

  function buildBilingualTxt(ep, list) {
    const header = [
      `Title: ${ep.display_title || ep.title || ""}`,
      `Program: ${ep.feed_name || ""}`,
      `Published: ${ep.pub_display || ""}`,
      "================================================================",
      "",
    ];
    const groups = groupSubtitlesByParagraph(list);
    groups.forEach((g, pi) => {
      header.push(`[第 ${pi + 1} 段 · ${formatTime(g.start)} - ${formatTime(g.end)}]`);
      header.push(g.items.map(({ item }) => (item.en || "").trim()).filter(Boolean).join(" "));
      const zhText = g.items.map(({ item }) => (item.zh || "").trim()).filter(Boolean).join("");
      if (zhText) header.push(zhText);
      header.push("");
    });
    return header.join("\n");
  }

  const CRC_TABLE = (() => {
    const tbl = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      tbl[n] = c >>> 0;
    }
    return tbl;
  })();

  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  function buildStoreZip(files) {
    const enc = new TextEncoder();
    const localParts = [];
    const centralParts = [];
    let offset = 0;
    for (const f of files) {
      const nameBytes = enc.encode(f.name);
      const data = f.data;
      const crc = crc32(data);
      const localHdr = new Uint8Array(30 + nameBytes.length);
      const lv = new DataView(localHdr.buffer);
      lv.setUint32(0, 0x04034b50, true);
      lv.setUint16(4, 20, true);
      lv.setUint16(6, 0x0800, true);
      lv.setUint32(14, crc, true);
      lv.setUint32(18, data.length, true);
      lv.setUint32(22, data.length, true);
      lv.setUint16(26, nameBytes.length, true);
      localHdr.set(nameBytes, 30);
      localParts.push(localHdr, data);

      const centralHdr = new Uint8Array(46 + nameBytes.length);
      const cv = new DataView(centralHdr.buffer);
      cv.setUint32(0, 0x02014b50, true);
      cv.setUint16(4, 20, true);
      cv.setUint16(6, 20, true);
      cv.setUint16(8, 0x0800, true);
      cv.setUint32(16, crc, true);
      cv.setUint32(20, data.length, true);
      cv.setUint32(24, data.length, true);
      cv.setUint16(28, nameBytes.length, true);
      cv.setUint32(42, offset, true);
      centralHdr.set(nameBytes, 46);
      centralParts.push(centralHdr);
      offset += localHdr.length + data.length;
    }
    const centralSize = centralParts.reduce((s, p) => s + p.length, 0);
    const eocd = new Uint8Array(22);
    const ev = new DataView(eocd.buffer);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(8, files.length, true);
    ev.setUint16(10, files.length, true);
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);
    return new Blob([...localParts, ...centralParts, eocd], { type: "application/zip" });
  }

  function triggerBlobDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  function episodeAudioUrl(ep) {
    if (appMode === "api") return `/api/episodes/${encodeURIComponent(ep.id)}/audio`;
    if (ep.static_audio_path) return `./${ep.static_audio_path}`;
    return ep.remote_audio_url;
  }

  async function handleStaticDownload(kind) {
    if (!currentEpisode) return;
    const slug = safeSlug(currentEpisode);
    const enc = new TextEncoder();
    const bom = "\uFEFF";

    if (kind === "srt_en") {
      triggerBlobDownload(new Blob([bom + buildSrtText(subtitles, "en")], { type: "text/plain;charset=utf-8" }), `${slug}_en.srt`);
      showToast("已开始保存英文字幕");
      return;
    }
    if (kind === "srt_zh") {
      triggerBlobDownload(new Blob([bom + buildSrtText(subtitles, "zh")], { type: "text/plain;charset=utf-8" }), `${slug}_zh.srt`);
      showToast("已开始保存中文字幕");
      return;
    }
    if (kind === "srt_bilingual") {
      triggerBlobDownload(new Blob([bom + buildSrtText(subtitles, "bilingual")], { type: "text/plain;charset=utf-8" }), `${slug}_bilingual.srt`);
      showToast("已开始保存双语字幕");
      return;
    }
    if (kind === "txt") {
      triggerBlobDownload(new Blob([bom + buildBilingualTxt(currentEpisode, subtitles)], { type: "text/plain;charset=utf-8" }), `${slug}_bilingual.txt`);
      showToast("已开始保存双语对照文稿");
      return;
    }

    const audioUrl = episodeAudioUrl(currentEpisode);
    if (kind === "audio") {
      try {
        showToast("正在准备音频文件下载...");
        const resp = await fetch(audioUrl);
        if (!resp.ok) throw new Error("audio fetch failed");
        triggerBlobDownload(await resp.blob(), `${slug}.mp3`);
        showToast("已保存音频到本地");
      } catch (_) {
        window.open(audioUrl, "_blank", "noopener");
      }
      return;
    }

    showToast("正在打包音频与中英字幕...");
    const files = [];
    try {
      const resp = await fetch(audioUrl);
      if (resp.ok) files.push({ name: `${slug}.mp3`, data: new Uint8Array(await resp.arrayBuffer()) });
    } catch (_) {}

    if (subtitles.length > 0) {
      files.push({ name: `${slug}_en.srt`, data: enc.encode(bom + buildSrtText(subtitles, "en")) });
      files.push({ name: `${slug}_zh.srt`, data: enc.encode(bom + buildSrtText(subtitles, "zh")) });
      files.push({ name: `${slug}_bilingual.srt`, data: enc.encode(bom + buildSrtText(subtitles, "bilingual")) });
      files.push({ name: `${slug}_bilingual.txt`, data: enc.encode(bom + buildBilingualTxt(currentEpisode, subtitles)) });
    }
    if (!files.length) {
      showToast("暂无可打包的文件");
      return;
    }
    triggerBlobDownload(buildStoreZip(files), `${slug}.zip`);
    showToast("已开始保存 ZIP 打包文件");
  }

  function renderEpisodeSelect(selectedId) {
    episodeSelect.innerHTML = "";
    if (!episodes.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "暂无音频，请点击「同步」";
      episodeSelect.appendChild(opt);
      episodeIndexBadge.textContent = "0/0";
      return;
    }

    const groups = { twth: [], wr: [], ywt: [] };
    for (const ep of episodes) {
      if (!groups[ep.feed_key]) groups[ep.feed_key] = [];
      groups[ep.feed_key].push(ep);
    }

    for (const key of ["twth", "wr", "ywt"]) {
      const list = groups[key];
      if (!list || !list.length) continue;
      const og = document.createElement("optgroup");
      og.label = FEED_GROUP_LABELS[key] || key;
      list.forEach((ep, idx) => {
        const opt = document.createElement("option");
        opt.value = ep.id;
        const badge = ep.has_subtitles ? "✓" : (ep.status === "transcribing" || ep.status === "translating" ? "⏳" : "○");
        const latestTag = (key === "twth" && idx === 0) ? "[最新] " : "";
        const durTag = ep.duration ? ` (${formatTime(ep.duration)})` : "";
        opt.textContent = `${badge} ${latestTag}${ep.display_title}${durTag}`;
        if (ep.id === selectedId) opt.selected = true;
        og.appendChild(opt);
      });
      episodeSelect.appendChild(og);
    }

    const curIdx = episodes.findIndex((e) => e.id === selectedId);
    episodeIndexBadge.textContent = `${curIdx >= 0 ? curIdx + 1 : 1}/${episodes.length}`;
  }

  function updateDownloadMenuState() {
    const hasEp = Boolean(currentEpisode);
    const hasSubs = Boolean(currentEpisode && subtitles.length > 0);
    btnSave.disabled = !hasEp;
    saveDropdown.querySelectorAll(".save-item").forEach((item) => {
      const kind = item.dataset.download;
      if (!hasEp) item.disabled = true;
      else if (kind === "audio" || kind === "zip") item.disabled = false;
      else item.disabled = !hasSubs;
    });
  }

  function renderStatusPlaceholder(ep) {
    const pct = Math.max(4, Math.min(100, ep?.progress || 6));
    const msg = appMode === "static"
      ? (ep?.has_subtitles ? "正在加载中英双语字幕..." : "该期暂未预生成双语字幕")
      : (ep?.status_message || "正在准备中英双语字幕...");
    const isErr = ep?.status === "error";

    const html = isErr
      ? `<div class="status-placeholder">
           <div style="font-weight:600;color:var(--primary)">${msg}</div>
           <div style="font-size:12px">${ep.error || ""}</div>
           <button class="btn btn-retry" type="button">重新生成字幕</button>
         </div>`
      : `<div class="status-placeholder">
           <div style="font-weight:600;color:var(--text)">${msg}</div>
           ${appMode === "api" ? `<div class="status-bar-track"><div class="status-bar-fill" style="width:${pct}%"></div></div>` : ""}
           <div style="font-size:12px">您可以先点击「播放」收听音频</div>
         </div>`;

    panelSplit.innerHTML = html;
    panelStack.innerHTML = html;
    counterEn.textContent = "第 0 / 0 段";
    counterZh.textContent = "第 0 / 0 段";
    counterStack.textContent = "第 0 / 0 段";

    if (appMode === "api") {
      document.querySelectorAll(".btn-retry").forEach((b) => {
        b.addEventListener("click", async () => {
          if (!currentEpisode) return;
          await fetch(`/api/episodes/${encodeURIComponent(currentEpisode.id)}/process`, { method: "POST" });
          startPollingEpisode(currentEpisode.id);
        });
      });
    }
  }

  function renderSubtitles() {
    panelSplit.innerHTML = "";
    panelStack.innerHTML = "";
    paragraphs = [];
    sentenceToPara = [];
    splitEnSpans = [];
    splitZhSpans = [];
    stackEnSpans = [];
    stackZhSpans = [];
    splitRowEls = [];
    stackCardEls = [];
    activeIndex = -1;
    activeParaIndex = -1;
    loopParaIndex = 0;

    if (!subtitles.length) {
      renderStatusPlaceholder(currentEpisode);
      updateDownloadMenuState();
      return;
    }

    paragraphs = groupSubtitlesByParagraph(subtitles);
    const fragSplit = document.createDocumentFragment();
    const fragStack = document.createDocumentFragment();

    paragraphs.forEach((para, pIdx) => {
      const metaText = `第 ${pIdx + 1} 段 · ${formatTime(para.start)} - ${formatTime(para.end)}`;

      const pairRow = document.createElement("div");
      pairRow.className = "para-pair-row";
      pairRow.dataset.paraIndex = String(pIdx);

      const enCard = document.createElement("article");
      enCard.className = "para-card para-card-en";
      const enMeta = document.createElement("div");
      enMeta.className = "para-meta";
      enMeta.textContent = metaText;
      const enProse = document.createElement("p");
      enProse.className = "para-prose";

      const zhCard = document.createElement("article");
      zhCard.className = "para-card para-card-zh";
      const zhMeta = document.createElement("div");
      zhMeta.className = "para-meta";
      zhMeta.textContent = metaText;
      const zhProse = document.createElement("p");
      zhProse.className = "para-prose";

      const stackCard = document.createElement("article");
      stackCard.className = "para-card stack-para-card";
      stackCard.dataset.paraIndex = String(pIdx);
      const stackMeta = document.createElement("div");
      stackMeta.className = "para-meta";
      stackMeta.textContent = metaText;
      const stackEnProse = document.createElement("p");
      stackEnProse.className = "para-prose";
      const stackDiv = document.createElement("div");
      stackDiv.className = "stack-divider";
      const stackZhProse = document.createElement("p");
      stackZhProse.className = "para-prose";

      para.items.forEach(({ idx, item }, localIdx) => {
        sentenceToPara[idx] = pIdx;
        const onSentClick = () => {
          loopParaIndex = pIdx;
          seekTo(item.start + 0.05, true);
          if (audio.paused) audio.play().catch(() => {});
        };

        const enText = localIdx > 0 ? ` ${item.en || ""}` : (item.en || "");
        const zhText = item.zh || item.en || "";

        const spEn = document.createElement("span");
        spEn.className = "sent-span";
        spEn.dataset.index = String(idx);
        spEn.textContent = enText;
        spEn.addEventListener("click", onSentClick);
        spEn.addEventListener("mouseenter", () => setPairHover(idx, true));
        spEn.addEventListener("mouseleave", () => setPairHover(idx, false));

        const spZh = document.createElement("span");
        spZh.className = "sent-span";
        spZh.dataset.index = String(idx);
        spZh.textContent = zhText;
        spZh.addEventListener("click", onSentClick);
        spZh.addEventListener("mouseenter", () => setPairHover(idx, true));
        spZh.addEventListener("mouseleave", () => setPairHover(idx, false));

        const stEn = document.createElement("span");
        stEn.className = "sent-span";
        stEn.dataset.index = String(idx);
        stEn.textContent = enText;
        stEn.addEventListener("click", onSentClick);

        const stZh = document.createElement("span");
        stZh.className = "sent-span";
        stZh.dataset.index = String(idx);
        stZh.textContent = zhText;
        stZh.addEventListener("click", onSentClick);

        enProse.appendChild(spEn);
        zhProse.appendChild(spZh);
        stackEnProse.appendChild(stEn);
        stackZhProse.appendChild(stZh);

        splitEnSpans[idx] = spEn;
        splitZhSpans[idx] = spZh;
        stackEnSpans[idx] = stEn;
        stackZhSpans[idx] = stZh;
      });

      enCard.appendChild(enMeta);
      enCard.appendChild(enProse);
      zhCard.appendChild(zhMeta);
      zhCard.appendChild(zhProse);
      pairRow.appendChild(enCard);
      pairRow.appendChild(zhCard);
      splitRowEls[pIdx] = pairRow;
      fragSplit.appendChild(pairRow);

      stackCard.appendChild(stackMeta);
      stackCard.appendChild(stackEnProse);
      stackCard.appendChild(stackDiv);
      stackCard.appendChild(stackZhProse);
      stackCardEls[pIdx] = stackCard;
      fragStack.appendChild(stackCard);
    });

    panelSplit.appendChild(fragSplit);
    panelStack.appendChild(fragStack);

    const initCounter = `第 1 / ${paragraphs.length} 段`;
    counterEn.textContent = initCounter;
    counterZh.textContent = initCounter;
    counterStack.textContent = initCounter;
    updateDownloadMenuState();
    syncSubtitleHighlight(true);
  }

  function setPairHover(idx, on) {
    if (idx === activeIndex) return;
    splitEnSpans[idx]?.classList.toggle("pair-hover", on);
    splitZhSpans[idx]?.classList.toggle("pair-hover", on);
  }

  function scrollContainerToElement(container, el, smooth) {
    if (!container || !el) return;
    const cRect = container.getBoundingClientRect();
    const eRect = el.getBoundingClientRect();
    const targetTop = Math.max(0, container.scrollTop + (eRect.top - cRect.top) - container.clientHeight * 0.28);
    container.scrollTo({ top: targetTop, behavior: smooth ? "smooth" : "auto" });
  }

  function scrollPanelsTo(idx, smooth = true) {
    if (layoutMode === "stack") {
      const targetEl = stackEnSpans[idx] || stackCardEls[sentenceToPara[idx]];
      scrollContainerToElement(panelStack, targetEl, smooth);
      return;
    }
    const targetEl = splitEnSpans[idx] || splitRowEls[sentenceToPara[idx]];
    scrollContainerToElement(panelSplit, targetEl, smooth);
  }

  function findActiveIndex(t) {
    if (!subtitles.length) return -1;
    for (let i = 0; i < subtitles.length; i++) {
      if (t >= subtitles[i].start && t < subtitles[i].end) return i;
    }
    for (let i = subtitles.length - 1; i >= 0; i--) {
      if (t >= subtitles[i].start) return i;
    }
    return 0;
  }

  function syncSubtitleHighlight(forceScroll = false) {
    if (!subtitles.length) return;
    const idx = findActiveIndex(audio.currentTime || 0);
    if (idx === -1) return;

    if (idx !== activeIndex || forceScroll) {
      if (activeIndex >= 0) {
        splitEnSpans[activeIndex]?.classList.remove("active");
        splitZhSpans[activeIndex]?.classList.remove("active");
        stackEnSpans[activeIndex]?.classList.remove("active");
        stackZhSpans[activeIndex]?.classList.remove("active");
      }
      if (activeParaIndex >= 0) {
        splitRowEls[activeParaIndex]?.classList.remove("para-active");
        stackCardEls[activeParaIndex]?.classList.remove("para-active");
      }

      activeIndex = idx;
      activeParaIndex = sentenceToPara[activeIndex] ?? 0;

      splitRowEls[activeParaIndex]?.classList.add("para-active");
      stackCardEls[activeParaIndex]?.classList.add("para-active");

      splitEnSpans[activeIndex]?.classList.remove("pair-hover");
      splitZhSpans[activeIndex]?.classList.remove("pair-hover");
      splitEnSpans[activeIndex]?.classList.add("active");
      splitZhSpans[activeIndex]?.classList.add("active");
      stackEnSpans[activeIndex]?.classList.add("active");
      stackZhSpans[activeIndex]?.classList.add("active");

      const text = `第 ${activeParaIndex + 1} / ${paragraphs.length} 段`;
      counterEn.textContent = text;
      counterZh.textContent = text;
      counterStack.textContent = text;

      // 仅在「同步滚动」模式下字幕自动随音频滚动；「自由滚动」下不强行拉动滚动条
      if (scrollMode === "sync") {
        scrollPanelsTo(activeIndex, !forceScroll);
      }
    }
  }

  function updateProgressUI() {
    const dur = effectiveDuration();
    const cur = audio.currentTime || 0;
    const pct = dur > 0 ? Math.max(0, Math.min(100, (cur / dur) * 100)) : 0;

    progressFill.style.width = `${pct}%`;
    progressThumb.style.left = `${pct}%`;
    progressHit.setAttribute("aria-valuenow", String(Math.round(pct)));
    timeCurrent.textContent = formatTime(cur);
    timeDuration.textContent = formatTime(dur);

    if (audio.buffered.length > 0 && dur > 0) {
      const end = audio.buffered.end(audio.buffered.length - 1);
      progressBuffer.style.width = `${Math.min(100, (end / dur) * 100)}%`;
    }
  }

  function updatePlayButton() {
    const playing = !audio.paused && !audio.ended;
    iconPlay.style.display = playing ? "none" : "block";
    iconPause.style.display = playing ? "block" : "none";
    labelPlay.textContent = playing ? "暂停" : "播放";
    if ("mediaSession" in navigator) {
      navigator.mediaSession.playbackState = playing ? "playing" : "paused";
    }
  }

  function seekTo(sec, updateLoopTarget = false) {
    const dur = effectiveDuration();
    const target = Math.max(0, dur > 0 ? Math.min(dur - 0.05, sec) : Math.max(0, sec));
    audio.currentTime = target;
    updateProgressUI();
    syncSubtitleHighlight(false);
    if (updateLoopTarget && activeParaIndex >= 0) {
      loopParaIndex = activeParaIndex;
    }
    updateMediaSessionPosition();
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function startPollingEpisode(epId) {
    if (appMode !== "api") return;
    stopPolling();
    const poll = async () => {
      if (!currentEpisode || currentEpisode.id !== epId) return;
      try {
        const res = await fetch(`/api/episodes/${encodeURIComponent(epId)}?process=false`);
        if (!res.ok) return;
        const data = await res.json();
        currentEpisode = data.episode;
        const listIdx = episodes.findIndex((e) => e.id === epId);
        if (listIdx >= 0) episodes[listIdx] = currentEpisode;

        if (data.subtitles && data.subtitles.length > 0) {
          subtitles = data.subtitles;
          renderEpisodeSelect(epId);
          renderSubtitles();
          showToast(`双语字幕已就绪（共 ${paragraphs.length} 段）`);
          return;
        }
        renderStatusPlaceholder(currentEpisode);
        if (["queued", "downloading", "transcribing", "translating"].includes(currentEpisode.status)) {
          pollTimer = setTimeout(poll, 1600);
        }
      } catch (_) {
        pollTimer = setTimeout(poll, 3000);
      }
    };
    pollTimer = setTimeout(poll, 1200);
  }

  async function selectEpisode(epId, autoPlay = false) {
    if (!epId) return;
    stopPolling();

    try {
      if (appMode === "api") {
        const res = await fetch(`/api/episodes/${encodeURIComponent(epId)}?process=true`);
        if (!res.ok) throw new Error("加载期数失败");
        const data = await res.json();
        currentEpisode = data.episode;
        subtitles = data.subtitles || [];
      } else {
        const found = episodes.find((e) => e.id === epId);
        if (!found) throw new Error("未找到该期音频");
        currentEpisode = found;
        subtitles = [];
        if (found.static_subtitle_path || found.has_subtitles) {
          const subPath = found.static_subtitle_path ? `./${found.static_subtitle_path}` : `./data/subtitles/${encodeURIComponent(epId)}.json`;
          const sRes = await fetch(`${subPath}?v=${encodeURIComponent(found.pub_ts || Date.now())}`);
          if (sRes.ok) subtitles = await sRes.json();
        }
      }

      const listIdx = episodes.findIndex((e) => e.id === epId);
      if (listIdx >= 0) episodes[listIdx] = currentEpisode;
      renderEpisodeSelect(epId);

      episodeMetaHint.textContent = `${currentEpisode.feed_name} · 发布于 ${currentEpisode.pub_display}`;
      audio.src = episodeAudioUrl(currentEpisode);
      audio.playbackRate = SPEEDS[speedIdx];
      audio.load();
      updatePlayButton();
      updateProgressUI();
      updateMediaSessionMetadata();

      if (subtitles.length > 0) {
        renderSubtitles();
      } else {
        renderStatusPlaceholder(currentEpisode);
        updateDownloadMenuState();
        startPollingEpisode(epId);
      }

      pendingAutoPlay = Boolean(autoPlay);
      if (autoPlay) {
        audio.play().then(() => { pendingAutoPlay = false; }).catch(() => {});
      }
    } catch (err) {
      showToast(`加载失败: ${err.message}`);
    }
  }

  async function detectModeAndLoad(preserveSelection = false) {
    try {
      const res = await fetch("/api/episodes", { cache: "no-store" });
      if (res.ok) {
        const ct = res.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          const data = await res.json();
          if (Array.isArray(data.episodes)) {
            appMode = "api";
            episodes = data.episodes;
            return finishLoadEpisodes(preserveSelection);
          }
        }
      }
    } catch (_) {}

    appMode = "static";
    const sRes = await fetch(`./data/episodes.json?t=${Date.now()}`, { cache: "no-store" });
    if (!sRes.ok) throw new Error("无法加载节目归档清单");
    const sData = await sRes.json();
    episodes = Array.isArray(sData) ? sData : (sData.episodes || []);
    return finishLoadEpisodes(preserveSelection);
  }

  async function finishLoadEpisodes(preserveSelection) {
    if (!episodes.length) {
      renderEpisodeSelect("");
      return;
    }
    const wantedId = (preserveSelection && currentEpisode && episodes.some((e) => e.id === currentEpisode.id))
      ? currentEpisode.id
      : episodes[0].id;
    renderEpisodeSelect(wantedId);
    if (!currentEpisode || currentEpisode.id !== wantedId) {
      await selectEpisode(wantedId, false);
    }
  }

  // 基础控件事件绑定
  episodeSelect.addEventListener("change", () => {
    const epId = episodeSelect.value;
    if (epId) selectEpisode(epId, false);
  });

  btnPlay.addEventListener("click", () => {
    if (!currentEpisode) return;
    if (audio.paused) {
      audio.play().catch(() => showToast("请稍候音频缓冲完成"));
    } else {
      audio.pause();
    }
  });

  btnSpeed.addEventListener("click", () => {
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    const rate = SPEEDS[speedIdx];
    audio.playbackRate = rate;
    btnSpeed.textContent = `${rate.toFixed(2).replace(/\.00$/, ".0")}x`;
    updateMediaSessionPosition();
  });

  btnMute.addEventListener("click", () => {
    audio.muted = !audio.muted;
    iconVol.style.display = audio.muted ? "none" : "block";
    iconMuted.style.display = audio.muted ? "block" : "none";
  });

  volumeSlider.addEventListener("input", () => {
    const v = parseFloat(volumeSlider.value);
    audio.volume = v;
    audio.muted = v === 0;
    iconVol.style.display = audio.muted ? "none" : "block";
    iconMuted.style.display = audio.muted ? "block" : "none";
  });

  btnSave.addEventListener("click", (e) => {
    e.stopPropagation();
    updateDownloadMenuState();
    saveDropdown.classList.toggle("open");
  });

  document.addEventListener("click", (e) => {
    if (!saveDropdown.contains(e.target) && e.target !== btnSave) {
      saveDropdown.classList.remove("open");
    }
  });

  saveDropdown.querySelectorAll(".save-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!currentEpisode) return;
      const kind = btn.dataset.download;
      saveDropdown.classList.remove("open");
      if (appMode === "static") {
        handleStaticDownload(kind);
        return;
      }
      const url = `/api/episodes/${encodeURIComponent(currentEpisode.id)}/download?kind=${encodeURIComponent(kind)}`;
      const a = document.createElement("a");
      a.href = url;
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
      showToast(kind === "zip" ? "开始打包下载音频与中英字幕..." : "已开始下载到本地");
    });
  });

  btnSync.addEventListener("click", async () => {
    btnSync.disabled = true;
    iconSync.classList.add("spin");
    labelSync.textContent = "同步中";
    try {
      if (appMode === "api") {
        const res = await fetch("/api/sync", { method: "POST" });
        const data = await res.json();
        episodes = data.episodes || episodes;
        if (episodes.length > 0) {
          const latestTwth = episodes.find((e) => e.feed_key === "twth") || episodes[0];
          if (data.new_episodes > 0 && latestTwth.id !== currentEpisode?.id) {
            showToast(`发现 ${data.new_episodes} 期新音频，已切换至最新一期`);
            await selectEpisode(latestTwth.id, false);
          } else {
            renderEpisodeSelect(currentEpisode?.id || episodes[0].id);
            showToast("已是 CBC 最新一期音频");
          }
        }
      } else {
        const prevLatest = episodes[0]?.id;
        await detectModeAndLoad(true);
        const nowLatest = episodes[0]?.id;
        if (nowLatest && nowLatest !== prevLatest) {
          showToast("已同步到最新一期 CBC 广播");
          await selectEpisode(nowLatest, false);
        } else {
          showToast("已刷新列表（云端每小时自动更新）");
        }
      }
    } catch (_) {
      showToast("同步失败，请稍后重试");
    } finally {
      btnSync.disabled = false;
      iconSync.classList.remove("spin");
      labelSync.textContent = "同步";
    }
  });

  // 进度条拖拽与悬停预览
  function timeFromClientX(clientX) {
    const rect = progressHit.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return ratio * effectiveDuration();
  }

  progressHit.addEventListener("pointerdown", (e) => {
    if (effectiveDuration() <= 0) return;
    isDragging = true;
    progressHit.classList.add("dragging");
    progressHit.setPointerCapture(e.pointerId);
    seekTo(timeFromClientX(e.clientX), true);
  });

  progressHit.addEventListener("pointermove", (e) => {
    const dur = effectiveDuration();
    if (dur <= 0) return;
    const t = timeFromClientX(e.clientX);
    hoverPreview.textContent = `预览 ${formatTime(t)}`;
    hoverPreview.classList.add("visible");
    if (isDragging) seekTo(t, true);
  });

  progressHit.addEventListener("pointerup", (e) => {
    if (!isDragging) return;
    isDragging = false;
    progressHit.classList.remove("dragging");
    progressHit.releasePointerCapture(e.pointerId);
  });

  progressHit.addEventListener("pointerleave", () => {
    if (!isDragging) hoverPreview.classList.remove("visible");
  });

  // 音频事件
  audio.addEventListener("play", () => {
    updatePlayButton();
    updateMediaSessionPosition();
  });
  audio.addEventListener("pause", () => {
    pendingAutoPlay = false;
    updatePlayButton();
    updateMediaSessionPosition();
  });
  audio.addEventListener("ended", () => {
    updatePlayButton();
    advanceEpisode(1, false);
  });
  audio.addEventListener("canplay", () => {
    if (pendingAutoPlay && audio.paused) {
      pendingAutoPlay = false;
      audio.play().catch(() => {});
    }
  });
  audio.addEventListener("loadedmetadata", () => {
    updateProgressUI();
    syncSubtitleHighlight(true);
    updateMediaSessionPosition();
  });
  audio.addEventListener("progress", updateProgressUI);
  audio.addEventListener("timeupdate", () => {
    if (!isDragging) updateProgressUI();
    checkParagraphLoop();
    syncSubtitleHighlight(false);
  });

  // 全局键盘快捷键
  window.addEventListener("keydown", (e) => {
    const tag = (e.target?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (e.code === "Space") {
      e.preventDefault();
      btnPlay.click();
    } else if (e.code === "ArrowLeft") {
      e.preventDefault();
      jumpToParagraph(-1);
    } else if (e.code === "ArrowRight") {
      e.preventDefault();
      jumpToParagraph(1);
    }
  });

  async function boot() {
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        await detectModeAndLoad(false);
        if (episodes.length > 0) return;
      } catch (_) {}
      await new Promise((r) => setTimeout(r, 1500));
    }
  }
  boot();
})();
