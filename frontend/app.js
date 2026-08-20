"use strict";
/* Đọc & Nghe — logic giao diện + phát giọng đồng bộ từng câu. */

const $ = (s, r = document) => r.querySelector(s);
const api = (p, o) => fetch(p, o);

const LS = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

/* ------------------------------ Trạng thái ------------------------------ */
const state = {
  book: null,          // dữ liệu đầy đủ của sách đang mở
  chapter: 0,          // chỉ số chương hiện tại
  units: [],           // [{text, el}] các đơn vị đọc trong chương
  pos: -1,             // đơn vị đang/đã chọn
  playing: false,
  loadingAudio: false,
  speed: LS.get("kv:speed", 0.85),
  audioCache: new Map(),   // text -> objectURL (theo chương)
  audioPromises: new Map(),// text -> Promise (gộp yêu cầu trùng đang chạy)
  ttsReady: false,
};

const audio = $("#audio");
// Giữ nguyên cao độ giọng khi đổi tốc độ (không bị méo/chói khi chậm/nhanh)
audio.preservesPitch = true;
audio.mozPreservesPitch = true;
audio.webkitPreservesPitch = true;

/* ------------------------------ Tiện ích ------------------------------- */
let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3200);
}

function colorFromId(id) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 42% 34%)`;
}

/* =============================== THƯ VIỆN =============================== */
async function loadStatus() {
  try {
    const s = await api("/api/status").then(r => r.json());
    state.ttsReady = !!(s.tts && s.tts.ready);
    const badge = $("#tts-badge");
    if (state.ttsReady) {
      badge.textContent = "Giọng: " + (s.tts.voice || "sẵn sàng");
      badge.className = "badge ok";
    } else {
      badge.textContent = "Chưa có giọng đọc";
      badge.className = "badge warn";
      badge.title = (s.tts && s.tts.error) || "Xem README để cài mô hình";
    }
  } catch {
    $("#tts-badge").textContent = "Mất kết nối máy chủ";
  }
}

async function loadLibrary() {
  let books = [];
  try { books = await api("/api/books").then(r => r.json()); }
  catch { toast("Không kết nối được máy chủ", true); }

  const shelf = $("#shelf");
  shelf.innerHTML = "";
  $("#library-empty").hidden = books.length > 0;

  for (const b of books) shelf.appendChild(bookCard(b));

  const add = document.createElement("div");
  add.className = "add-tile";
  add.innerHTML = `<div style="text-align:center"><div class="plus">＋</div><div>Thêm sách</div></div>`;
  add.onclick = () => $("#file-input").click();
  shelf.appendChild(add);
}

function bookCard(b) {
  const card = document.createElement("button");
  card.className = "card";
  const cover = document.createElement("div");
  cover.className = "cover";
  if (b.has_cover) {
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = `/api/books/${b.id}/cover`;
    img.onerror = () => { cover.innerHTML = genCover(b); };
    cover.appendChild(img);
  } else {
    cover.innerHTML = genCover(b);
  }
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML = `<div class="ct"></div><div class="ca"></div>`;
  meta.querySelector(".ct").textContent = b.title || b.id;
  meta.querySelector(".ca").textContent = b.author || "";
  card.append(cover, meta);
  card.onclick = () => openBook(b.id);
  return card;
}

function genCover(b) {
  const c = colorFromId(b.id);
  const initial = (b.title || "?").trim().charAt(0).toUpperCase();
  const el = document.createElement("div");
  el.className = "gen";
  el.style.background = `linear-gradient(160deg, ${c}, #201b30)`;
  el.innerHTML = `<div class="big"></div><div class="t"></div>`;
  el.querySelector(".big").textContent = initial;
  el.querySelector(".t").textContent = b.title || "";
  return el.outerHTML;
}

/* Upload + kéo thả */
$("#file-input").addEventListener("change", e => {
  const f = e.target.files[0];
  if (f) uploadBook(f);
  e.target.value = "";
});
["dragover", "dragenter"].forEach(ev =>
  document.addEventListener(ev, e => { e.preventDefault(); document.body.classList.add("drag-over"); }));
["dragleave", "drop"].forEach(ev =>
  document.addEventListener(ev, e => {
    e.preventDefault();
    if (ev === "drop") { const f = e.dataTransfer.files[0]; if (f) uploadBook(f); }
    document.body.classList.remove("drag-over");
  }));

async function uploadBook(file) {
  if (!file.name.toLowerCase().endsWith(".epub")) return toast("Chỉ nhận file .epub", true);
  toast("Đang thêm sách…");
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await api("/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || "Lỗi");
    toast("Đã thêm sách");
    loadLibrary();
  } catch (e) { toast("Không thêm được: " + e.message, true); }
}

/* =============================== TRÌNH ĐỌC =============================== */
async function openBook(id) {
  toast("Đang mở sách…");
  let book;
  try { book = await api(`/api/books/${id}`).then(r => { if (!r.ok) throw 0; return r.json(); }); }
  catch { return toast("Không mở được sách", true); }

  state.book = book;
  $("#r-title").textContent = book.title;

  const sel = $("#chapter-select");
  sel.innerHTML = "";
  book.chapters.forEach(c => {
    const o = document.createElement("option");
    o.value = c.index; o.textContent = `${c.index + 1}. ${c.title}`;
    sel.appendChild(o);
  });

  $("#library").hidden = true;
  $("#reader").hidden = false;
  applyTheme(LS.get("kv:theme", "light"));
  applyFontSize(LS.get("kv:size", 20));
  $("#speed").value = state.speed;
  $("#speed-val").textContent = state.speed.toFixed(2).replace(/0$/, "") + "×";

  const saved = LS.get("kv:pos:" + id, { chapter: 0, unit: -1 });
  renderChapter(saved.chapter || 0, saved.unit ?? -1);
}

function renderChapter(chIndex, startUnit = -1) {
  stopPlayback();
  clearAudioCache();
  state.chapter = chIndex;
  $("#chapter-select").value = chIndex;
  const ch = state.book.chapters[chIndex];

  const inner = document.createElement("div");
  inner.className = "page-inner";
  const units = [];

  const addUnit = (el, text) => { el.classList.add("s"); el.dataset.i = units.length; units.push({ text, el }); };

  const h = document.createElement("h2");
  h.className = "ch-title";
  h.textContent = ch.title;
  addUnit(h, ch.title);
  inner.appendChild(h);

  for (const block of ch.blocks) {
    if (block.type === "h") {
      const d = document.createElement("div");
      d.className = "h";
      d.textContent = block.text;
      addUnit(d, block.text);
      inner.appendChild(d);
    } else {
      const p = document.createElement("p");
      block.sentences.forEach((s, i) => {
        const span = document.createElement("span");
        span.textContent = s + (i < block.sentences.length - 1 ? " " : "");
        addUnit(span, s);
        p.appendChild(span);
      });
      inner.appendChild(p);
    }
  }

  const page = $("#page");
  page.innerHTML = "";
  page.appendChild(inner);
  page.scrollTop = 0;

  state.units = units;
  state.pos = -1;

  inner.addEventListener("click", e => {
    const el = e.target.closest(".s");
    if (!el) return;
    playFrom(parseInt(el.dataset.i, 10));
  });

  if (startUnit >= 0 && startUnit < units.length) {
    setActive(startUnit, false);
    units[startUnit].el.scrollIntoView({ block: "center" });
  }
  updateProgress();
  prefetchAhead(startUnit >= 0 ? startUnit : 0, 2);  // sẵn sàng cho lần bấm phát đầu
}

/* ---------------------------- Điều khiển đọc ---------------------------- */
function setActive(i, scroll = true) {
  if (state.pos >= 0 && state.units[state.pos]) {
    state.units[state.pos].el.classList.remove("active");
    state.units[state.pos].el.classList.add("done");
  }
  state.pos = i;
  const u = state.units[i];
  if (!u) return;
  u.el.classList.remove("done");
  u.el.classList.add("active");
  $("#now-reading").textContent = u.text;
  if (scroll) ensureVisible(u.el);
  savePos();
  updateProgress();
}

function ensureVisible(el) {
  const page = $("#page");
  const r = el.getBoundingClientRect();
  const pr = page.getBoundingClientRect();
  if (r.top < pr.top + 80 || r.bottom > pr.bottom - 80) {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

async function fetchAudio(text) {
  if (state.audioCache.has(text)) return state.audioCache.get(text);
  if (state.audioPromises.has(text)) return state.audioPromises.get(text);
  const p = (async () => {
    const r = await api("/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (r.status === 503) { const j = await r.json(); throw new Error(j.error || "Chưa có giọng đọc"); }
    if (!r.ok) {
      let msg = "Lỗi tổng hợp giọng";
      try { const j = await r.json(); if (j.detail) msg = j.detail; } catch {}
      throw new Error(msg);
    }
    const url = URL.createObjectURL(await r.blob());
    state.audioCache.set(text, url);
    return url;
  })();
  state.audioPromises.set(text, p);
  p.catch(() => {}).finally(() => state.audioPromises.delete(text));
  return p;
}

function prefetch(i) {
  const u = state.units[i];
  if (u && !state.audioCache.has(u.text)) fetchAudio(u.text).catch(() => {});
}

function prefetchAhead(from, n = 2) {
  for (let k = 0; k < n; k++) prefetch(from + k);
}

async function playUnit(i) {
  if (i < 0 || i >= state.units.length) return endOfChapter();
  setActive(i);
  const playBtn = $("#play-btn");
  try {
    state.loadingAudio = true;
    playBtn.classList.add("loading");
    const url = await fetchAudio(state.units[i].text);
    state.loadingAudio = false;
    playBtn.classList.remove("loading");
    if (!state.playing) return;             // bị dừng trong lúc chờ
    audio.src = url;
    audio.playbackRate = state.speed;
    await audio.play();
    prefetchAhead(i + 1, 2);                  // nạp trước 2 cụm kế cho mượt
  } catch (e) {
    state.loadingAudio = false;
    playBtn.classList.remove("loading");
    setPlaying(false);
    toast(e.message + " — xem README để cài giọng.", true);
  }
}

audio.addEventListener("ended", () => {
  if (!state.playing) return;
  if (state.pos + 1 < state.units.length) playUnit(state.pos + 1);
  else endOfChapter();
});

function endOfChapter() {
  if (state.chapter + 1 < state.book.chapters.length) {
    const next = state.chapter + 1;
    renderChapter(next, -1);
    setPlaying(true);
    playUnit(0);
  } else {
    setPlaying(false);
    toast("Đã đọc hết sách.");
  }
}

function setPlaying(v) {
  state.playing = v;
  $("#play-btn").textContent = v ? "⏸" : "▶";
}

function togglePlay() {
  if (state.playing) {
    setPlaying(false);
    audio.pause();
  } else {
    setPlaying(true);
    if (state.pos < 0) playUnit(0);
    else if (audio.src && audio.currentTime > 0 && !audio.ended) {
      audio.playbackRate = state.speed; audio.play();
    } else playUnit(state.pos);
  }
}

function playFrom(i) { setPlaying(true); playUnit(i); }

function stopPlayback() { setPlaying(false); audio.pause(); }

function step(delta) {
  const t = Math.min(Math.max((state.pos < 0 ? 0 : state.pos) + delta, 0), state.units.length - 1);
  if (state.playing) playUnit(t); else { setActive(t); }
}

function clearAudioCache() {
  for (const url of state.audioCache.values()) URL.revokeObjectURL(url);
  state.audioCache.clear();
  state.audioPromises.clear();
}

function updateProgress() {
  const total = state.book ? state.book.chapters.length : 0;
  const done = state.pos + 1;
  $("#progress-txt").textContent =
    `Chương ${state.chapter + 1}/${total} · câu ${Math.max(done, 0)}/${state.units.length}`;
}

function savePos() {
  if (state.book) LS.set("kv:pos:" + state.book.id, { chapter: state.chapter, unit: state.pos });
}

/* ------------------------------ Theme / cỡ chữ ------------------------------ */
function applyTheme(t) {
  $("#reader").dataset.theme = t;
  document.querySelectorAll(".theme-btn").forEach(b => b.classList.toggle("active", b.dataset.theme === t));
  LS.set("kv:theme", t);
}
function applyFontSize(px) {
  px = Math.min(Math.max(px, 15), 30);
  document.documentElement.style.setProperty("--reading-size", px + "px");
  LS.set("kv:size", px);
}

/* -------------------------------- Sự kiện -------------------------------- */
$("#back-btn").onclick = () => {
  stopPlayback(); clearAudioCache();
  $("#reader").hidden = true; $("#library").hidden = false;
  loadLibrary();
};
$("#play-btn").onclick = togglePlay;
$("#prev-btn").onclick = () => step(-1);
$("#next-btn").onclick = () => step(1);
$("#chapter-select").onchange = e => renderChapter(parseInt(e.target.value, 10), -1);
$("#speed").addEventListener("input", e => {
  state.speed = parseFloat(e.target.value);
  audio.playbackRate = state.speed;
  $("#speed-val").textContent = state.speed.toFixed(2).replace(/0$/, "") + "×";
  LS.set("kv:speed", state.speed);
});
document.querySelectorAll(".theme-btn").forEach(b => b.onclick = () => applyTheme(b.dataset.theme));
document.querySelectorAll("[data-font]").forEach(b => b.onclick = () => {
  const cur = LS.get("kv:size", 20);
  applyFontSize(cur + (b.dataset.font === "inc" ? 1 : -1));
});

document.addEventListener("keydown", e => {
  if ($("#reader").hidden) return;
  if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  else if (e.code === "ArrowRight") step(1);
  else if (e.code === "ArrowLeft") step(-1);
});

/* --------------------------------- Khởi động --------------------------------- */
async function loadVoices() {
  let data;
  try { data = await api("/api/voices").then(r => r.json()); } catch { return; }
  const sel = $("#voice-select");
  if (!sel) return;
  if (data.provider !== "vieneu" || !data.voices || !data.voices.length) {
    sel.hidden = true;
    return;
  }
  sel.innerHTML = "";
  for (const v of data.voices) {
    const o = document.createElement("option");
    o.value = v.id;
    o.textContent = v.label || v.id;
    if (v.id === data.current) o.selected = true;
    sel.appendChild(o);
  }
  sel.hidden = false;
  sel.onchange = async () => {
    const vid = sel.value;
    const wasPlaying = state.playing;
    stopPlayback();
    try {
      const r = await api("/api/voice", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_id: vid }),
      });
      if (!r.ok) throw new Error();
      const j = await r.json();
      clearAudioCache();
      toast("Đã đổi giọng: " + (j.voice || vid));
      if (wasPlaying && state.pos >= 0) playFrom(state.pos);
    } catch { toast("Không đổi được giọng", true); }
  };

  // Dropdown "mượn ngữ điệu" cho giọng nhân bản
  const blendSel = $("#blend-select");
  if (blendSel) {
    blendSel.innerHTML = "";
    const none = document.createElement("option");
    none.value = ""; none.textContent = "Ngữ điệu: gốc (không mượn)";
    blendSel.appendChild(none);
    for (const v of data.voices) {
      const o = document.createElement("option");
      o.value = v.id; o.textContent = "Ngữ điệu: " + (v.label || v.id);
      if (v.id === data.blend) o.selected = true;
      blendSel.appendChild(o);
    }
    blendSel.hidden = false;
    blendSel.onchange = async () => {
      const wasPlaying = state.playing;
      stopPlayback();
      try {
        const r = await api("/api/voice/blend", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice_id: blendSel.value || null }),
        });
        if (!r.ok) throw new Error();
        clearAudioCache();
        toast(blendSel.value ? ("Mượn ngữ điệu: " + blendSel.value) : "Về ngữ điệu gốc");
        if (wasPlaying && state.pos >= 0) playFrom(state.pos);
      } catch { toast("Không đổi được ngữ điệu", true); }
    };
  }

  // Nút nhân bản giọng từ file mẫu
  const cloneBtn = $("#clone-btn");
  const cloneInput = $("#clone-input");
  const denoiseLbl = $("#clone-denoise-lbl");
  const denoiseChk = $("#clone-denoise");
  if (cloneBtn && cloneInput) {
    cloneBtn.hidden = false;
    if (denoiseLbl) denoiseLbl.hidden = false;
    cloneBtn.onclick = () => cloneInput.click();
    cloneInput.onchange = async () => {
      const f = cloneInput.files[0];
      cloneInput.value = "";
      if (!f) return;
      const wasPlaying = state.playing;
      stopPlayback();
      toast("Đang nạp giọng mẫu…");
      const fd = new FormData();
      fd.append("file", f);
      fd.append("denoise", denoiseChk && denoiseChk.checked ? "1" : "0");
      try {
        const r = await api("/api/voice/clone", { method: "POST", body: fd });
        if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || "Lỗi"); }
        clearAudioCache();
        if (sel) sel.selectedIndex = -1;   // đang dùng giọng nhân bản
        toast("Đã dùng giọng nhân bản từ mẫu của bạn");
        if (wasPlaying && state.pos >= 0) playFrom(state.pos);
      } catch (e) { toast("Không nhân bản được: " + e.message, true); }
    };
  }
}

loadStatus();
loadVoices();
loadLibrary();
