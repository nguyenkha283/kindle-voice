"""sac_thai.py - gán sắc thái giọng đọc cho từng câu dựa vào ngữ cảnh đoạn văn.

OmniVoice không có tham số "cảm xúc": model bắt chước cách đọc của clip mẫu. Vì vậy mỗi
sắc thái = (một clip mẫu cùng giọng, đọc đúng sắc thái đó) + tốc độ + độ dài khoảng nghỉ.
Thiếu clip của sắc thái nào thì dùng clip dự phòng (cuối cùng là giọng gốc), nhưng
tốc độ và khoảng nghỉ của sắc thái đó vẫn được áp dụng.

Thứ tự quyết định sắc thái của một câu:
    1. OVERRIDES thủ công {số thứ tự câu: sắc thái}
    2. Cache nhãn đã gán (tags.json trên Drive, không gọi lại LLM)
    3. Một LLM đọc đoạn văn kèm vài đoạn trước đó làm ngữ cảnh: LocalScorer (model mở chạy
       trên GPU Colab, miễn phí, chấm điểm theo đoạn) hoặc ClaudeTagger (Claude API, tốn phí)
    4. Heuristic: câu là lời thoại (trong ngoặc kép / bắt đầu bằng gạch) -> doi_thoai
    5. trung_tinh
"""
import hashlib
import json
import re

# speed: hệ số tốc độ nói của OmniVoice (<1 chậm hơn). pause: nhân khoảng nghỉ sau câu.
REGISTERS = {
    "trung_tinh": dict(label="Kể chuyện, bình thản", speed=1.0, pause=1.0, fallback=()),
    "doi_thoai":  dict(label="Lời thoại nhân vật, sinh động", speed=1.0, pause=0.9,
                       fallback=("trung_tinh",)),
    "tinh_cam":   dict(label="Xúc động, buồn, thương, hoài niệm", speed=0.92, pause=1.25,
                       fallback=("trung_tinh",)),
    "kich_tinh":  dict(label="Căng thẳng, hồi hộp, sợ hãi, giận dữ", speed=1.06, pause=0.85,
                       fallback=("doi_thoai", "trung_tinh")),
    "vui_tuoi":   dict(label="Vui, hài hước, tươi tắn", speed=1.04, pause=0.9,
                       fallback=("doi_thoai", "trung_tinh")),
    "goi_cam":    dict(label="Thân mật, thì thầm, gợi cảm", speed=0.9, pause=1.35,
                       fallback=("tinh_cam", "trung_tinh")),
}
DEFAULT = "trung_tinh"


def _h(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def resolve(reg, clips):
    """Sắc thái -> tên clip sẽ dùng (theo chuỗi dự phòng). `clips` = các sắc thái đã có clip."""
    for name in (reg,) + REGISTERS[reg]["fallback"] + (DEFAULT,):
        if name in clips:
            return name
    return DEFAULT


def unit_key(say, voice, speed):
    """Khóa cache audio. Giọng gốc ở tốc độ 1.0 giữ đúng khóa cũ (hash của text),
    nên các câu đã render trước khi có tính năng sắc thái vẫn dùng lại được."""
    if voice == DEFAULT and speed == 1.0:
        return _h(say)
    return _h(f"{voice}|{speed:g}|{say}")


# --------------------------------------------------------------------------
# Heuristic (miễn phí)
# --------------------------------------------------------------------------
_QUOTE = re.compile(r"[\"“”«»].+?[\"“”«»]", re.S)
_DASH = re.compile(r"^\s*[—–-]\s*\S")


def heuristic(text):
    t = text.strip()
    if _DASH.match(t):
        return "doi_thoai"
    quoted = "".join(_QUOTE.findall(t))
    if quoted and len(quoted) >= 0.5 * len(t):
        return "doi_thoai"
    return None


# --------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------
_SYSTEM = """Bạn là đạo diễn lồng tiếng cho sách nói tiếng Việt. Mặc định mọi câu được đọc bằng \
giọng kể chuyện bình thản (trung_tinh). Nhiệm vụ của bạn: tìm những câu cần đọc bằng sắc thái KHÁC, \
dựa vào nội dung câu VÀ ngữ cảnh của đoạn văn (ai đang nói, cảnh đang diễn ra, cảm xúc của \
nhân vật/người kể).

Các sắc thái khác:
{regs}

Nguyên tắc:
- Chỉ liệt kê câu cần sắc thái khác; câu không liệt kê sẽ đọc trung_tinh. Không giải thích.
- Phần lớn sách là lời kể: chỉ chọn sắc thái khác khi cảm xúc trong câu rõ ràng.
- Giữ sắc thái ổn định trong một đoạn; chỉ đổi khi nội dung thật sự chuyển (vd lời kể -> lời \
thoại, hoặc cảm xúc dâng lên/lắng xuống). Đổi giọng liên tục từng câu nghe rất giả.
- Lời thoại mang cảm xúc mạnh thì chọn sắc thái cảm xúc đó thay vì doi_thoai.
- Tiêu đề, mục lục, chú thích: để trung_tinh."""

# USD / triệu token (input, output), theo trang Pricing ngày 2026-10-27. Kiểm tra lại khi giá đổi:
# https://platform.claude.com/docs/en/about-claude/pricing
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),   # prompt <= 100k token (mỗi lô ở đây nhỏ hơn nhiều)
}
CACHE_READ = {"claude-opus-5-5": 0.05, "claude-sonnet-5-5": 0.05, "claude-haiku-5-5": 0.10}


def _batches(units, size):
    """Chia theo ranh giới đoạn, mỗi lô khoảng `size` câu."""
    batch, cur_p = [], None
    for u in units:
        if batch and len(batch) >= size and u["p"] != cur_p:
            yield batch
            batch = []
        batch.append(u)
        cur_p = u["p"]
    if batch:
        yield batch


def build_prompt(batch, para_text, context_paras):
    """Các câu cần xét (đánh số, dòng trống = sang đoạn mới) kèm vài đoạn ngay trước làm ngữ cảnh."""
    first_p = batch[0]["p"]
    ctx = [para_text[p] for p in range(max(0, first_p - context_paras), first_p) if p in para_text]
    lines, cur_p = [], None
    for u in batch:
        if u["p"] != cur_p:
            lines.append("")
            cur_p = u["p"]
        lines.append(f"[{u['i']}] {u['text']}")
    return ("NGỮ CẢNH (các đoạn ngay trước, KHÔNG gán nhãn):\n"
            + ("\n\n".join(ctx) if ctx else "(đầu sách)")
            + "\n\nCÁC CÂU CẦN XÉT (dòng trống = sang đoạn mới):\n"
            + "\n".join(lines).strip())


class Usage:
    """Cộng dồn token thật từ response.usage và quy ra USD."""

    def __init__(self, model, batch):
        self.model, self.batch = model, batch
        self.inp = self.cache_w = self.cache_r = self.out = self.requests = 0

    def add(self, u):
        self.requests += 1
        self.inp += u.input_tokens or 0
        self.cache_w += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.cache_r += getattr(u, "cache_read_input_tokens", 0) or 0
        self.out += u.output_tokens or 0

    def usd(self):
        if self.model not in PRICES:
            return None
        pi, po = PRICES[self.model]
        cost = (self.inp * pi + self.cache_w * pi * 1.25
                + self.cache_r * pi * CACHE_READ[self.model] + self.out * po) / 1e6
        return cost * (0.5 if self.batch else 1.0)

    def __str__(self):
        usd = self.usd()
        return (f"{self.requests} request | input {self.inp:,} | output {self.out:,} (gồm suy nghĩ) token"
                + (f" | ≈ ${usd:.3f}" + (" (đã giảm 50% batch)" if self.batch else "") if usd is not None else ""))


class ClaudeTagger:
    """Gán nhãn theo lô: mỗi lần gửi một nhóm đoạn văn, kèm vài đoạn trước đó làm ngữ cảnh.

    use_batch=True: gửi tất cả lô qua Message Batches API (rẻ hơn 50%, thường xong trong vài
    phút tới 1 giờ, tối đa 24 giờ). Mã batch được lưu vào state_path, nên tắt ô/runtime chết
    rồi chạy lại vẫn lấy được kết quả, không gửi (và trả tiền) lần hai.
    """

    def __init__(self, api_key, model="claude-opus-5-5", effort="low", batch_units=150,
                 context_paras=3, use_batch=True, state_path=None, poll_s=30, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        self.client = client
        self.model = model
        self.effort = effort
        self.batch_units = batch_units
        self.context_paras = context_paras
        self.use_batch = use_batch
        self.state_path = state_path
        self.poll_s = poll_s
        self.usage = Usage(model, use_batch)
        others = [k for k in REGISTERS if k != DEFAULT]
        self.system = _SYSTEM.format(regs="\n".join(f"- {k}: {REGISTERS[k]['label']}" for k in others))
        self.schema = {
            "type": "object",
            "properties": {"labels": {"type": "array", "items": {
                "type": "object",
                "properties": {"i": {"type": "integer"}, "reg": {"type": "string", "enum": others}},
                "required": ["i", "reg"], "additionalProperties": False}}},
            "required": ["labels"], "additionalProperties": False,
        }

    def _batches(self, units):
        return _batches(units, self.batch_units)

    def _params(self, batch, para_text):
        prompt = build_prompt(batch, para_text, self.context_paras)
        return dict(model=self.model, max_tokens=16000, system=self.system,
                    output_config={"effort": self.effort,
                                   "format": {"type": "json_schema", "schema": self.schema}},
                    messages=[{"role": "user", "content": prompt}])

    def _parse(self, msg, ids):
        """Câu không được liệt kê -> trung_tinh. Trả về nhãn cho MỌI câu trong lô."""
        self.usage.add(msg.usage)
        if msg.stop_reason != "end_turn":
            raise RuntimeError(f"stop_reason={msg.stop_reason}")
        text = next(b.text for b in msg.content if b.type == "text")
        got = {i: DEFAULT for i in ids}
        got.update({d["i"]: d["reg"] for d in json.loads(text)["labels"] if d["i"] in got})
        return got

    def tag(self, units, para_text, on_batch=None, log=print):
        batches = list(self._batches(units))
        if self.use_batch:
            return self._tag_batch_api(batches, para_text, on_batch, log)
        out = {}
        for n, b in enumerate(batches, 1):
            try:
                msg = self.client.beta.messages.create(
                    **self._params(b, para_text),
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                got = self._parse(msg, [u["i"] for u in b])
            except Exception as e:  # lỗi một lô không làm hỏng cả lượt: lô đó dùng heuristic
                log(f"  lô {n}/{len(batches)} lỗi ({str(e)[:120]}), dùng heuristic")
                continue
            out.update(got)
            if on_batch:
                on_batch(got)
            log(f"  lô {n}/{len(batches)}: {sum(r != DEFAULT for r in got.values())}/{len(b)} câu có sắc thái riêng")
        return out

    def _tag_batch_api(self, batches, para_text, on_batch, log):
        import time
        from pathlib import Path
        state = None
        sp = Path(self.state_path) if self.state_path else None
        if sp and sp.exists():
            state = json.loads(sp.read_text(encoding="utf-8"))
            log(f"Tiếp tục batch đã gửi trước đó: {state['batch_id']}")
        if state is None:
            ids = {f"lo{n:04d}": [u["i"] for u in b] for n, b in enumerate(batches)}
            reqs = [{"custom_id": cid, "params": self._params(b, para_text)}
                    for cid, b in zip(ids, batches)]
            mb = self.client.messages.batches.create(requests=reqs)
            state = {"batch_id": mb.id, "ids": ids}
            if sp:
                sp.write_text(json.dumps(state), encoding="utf-8")
            log(f"Đã gửi {len(reqs)} lô qua Batch API ({mb.id}). Chờ kết quả... "
                "(có thể dừng ô này, lần chạy sau tự lấy tiếp)")
        while True:
            mb = self.client.messages.batches.retrieve(state["batch_id"])
            if mb.processing_status == "ended":
                break
            c = mb.request_counts
            log(f"  đang xử lý: xong {c.succeeded + c.errored}/{len(state['ids'])} lô")
            time.sleep(self.poll_s)
        out = {}
        for r in self.client.messages.batches.results(state["batch_id"]):
            ids = state["ids"].get(r.custom_id)
            if ids is None:
                continue
            if r.result.type != "succeeded":
                log(f"  {r.custom_id}: {r.result.type}, dùng heuristic")
                continue
            try:
                got = self._parse(r.result.message, ids)
            except Exception as e:
                log(f"  {r.custom_id} lỗi ({str(e)[:120]}), dùng heuristic")
                continue
            out.update(got)
            if on_batch:
                on_batch(got)
        if sp:
            sp.unlink(missing_ok=True)
        log(f"  xong: {len(out)} câu có nhãn từ Claude")
        return out


# --------------------------------------------------------------------------
# LLM chạy ngay trên GPU Colab (miễn phí API): chấm điểm theo ĐOẠN
# --------------------------------------------------------------------------
# Model nhỏ (vài tỉ tham số) bám từ khóa khi phải tự viết nhãn cho từng câu. Ở đây nó chỉ trả lời
# MỘT chữ số cho cả đoạn, và ta đọc thẳng xác suất của 5 chữ số đó (không sinh chữ), rồi chỉ nhận
# sắc thái cảm xúc khi xác suất vượt ngưỡng. Lời thoại (doi_thoai) do luật quyết định, không hỏi LLM.
EMOTIONS = ["trung_tinh", "tinh_cam", "kich_tinh", "vui_tuoi", "goi_cam"]   # đáp án 1..5

_SCORE_SYSTEM = """Bạn là đạo diễn lồng tiếng cho sách nói tiếng Việt. Đọc ĐOẠN CẦN XÉT (có ngữ cảnh \
đi trước) và chọn giọng đọc cho CẢ ĐOẠN:
1. Kể chuyện bình thản: lời kể, miêu tả, suy tư, nhận xét, giải thích, hồi tưởng
2. {tinh_cam}
3. {kich_tinh}
4. {vui_tuoi}
5. {goi_cam}

Phần lớn các đoạn trong sách là 1. Chỉ chọn 2-5 khi CẢ ĐOẠN được kể bằng cảm xúc đó một cách rõ \
ràng, mạnh mẽ, đến mức người đọc sách nói giỏi sẽ đổi hẳn giọng. Vài từ ngữ tiêu cực hay tích cực, \
lời châm biếm, nhận xét chê bai hay suy nghĩ u ám của người kể KHÔNG đủ để chọn 2-5.
Trả lời bằng đúng một chữ số."""


def _tail(text, n):
    return text if len(text) <= n else "…" + text[-n:]


class LocalScorer:
    """Chấm điểm sắc thái từng đoạn bằng một LLM mở trên GPU Colab.

    score() trả về {hash đoạn: [p1..p5]} (xác suất 5 đáp án, cộng lại = 1). Điểm được lưu lại,
    nên đổi ngưỡng (decide) không cần chạy lại model. Gọi close() xong để trả VRAM cho OmniVoice.
    """

    def __init__(self, model_id="Qwen/Qwen3-4B-Instruct-2507", context_paras=3, batch=8,
                 load_4bit=False, model=None, tokenizer=None):
        if model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            kw = {"dtype": torch.float16, "device_map": "cuda"}
            if load_4bit:   # model 7-14B vừa T4 khi lượng tử 4-bit (cần pip install bitsandbytes)
                from transformers import BitsAndBytesConfig
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4")
            model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
            model.eval()
        tokenizer.padding_side = "left"           # để vị trí cuối cùng luôn là token thật
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        self.model, self.tok = model, tokenizer
        self.context_paras = context_paras
        self.batch = batch
        self.system = _SCORE_SYSTEM.format(**{k: REGISTERS[k]["label"] for k in EMOTIONS[1:]})
        self.choice_ids = []
        for d in "12345":
            ids = tokenizer.encode(d, add_special_tokens=False)
            assert len(ids) == 1, f"tokenizer tách chữ số {d!r} thành {ids}"
            self.choice_ids.append(ids[0])

    def prompt(self, paras, k):
        ctx = [_tail(paras[j], 500) for j in range(max(0, k - self.context_paras), k)]
        msgs = [{"role": "system", "content": self.system},
                {"role": "user", "content":
                    "NGỮ CẢNH (các đoạn ngay trước):\n" + ("\n\n".join(ctx) if ctx else "(đầu sách)")
                    + "\n\nĐOẠN CẦN XÉT:\n" + paras[k][:1500]
                    + "\n\nGiọng đọc cho đoạn cần xét (1-5):"}]
        # enable_thinking=False: tắt chế độ suy nghĩ nếu dùng bản Qwen3 có chế độ này
        return self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                            enable_thinking=False)

    def _probs(self, texts):
        import torch
        enc = self.tok(texts, return_tensors="pt", padding=True,
                       add_special_tokens=False).to(self.model.device)
        with torch.no_grad():
            try:   # logits_to_keep=1: chỉ tính logits ở vị trí cuối (không thì tốn vài GB VRAM)
                out = self.model(**enc, use_cache=False, logits_to_keep=1)
            except TypeError:   # transformers cũ chưa có tham số này
                out = self.model(**enc, use_cache=False)
            logits = out.logits[:, -1, :]
        return torch.softmax(logits[:, self.choice_ids].float(), dim=-1).cpu().tolist()

    def score(self, paras, cache=None, save=None, min_chars=40, log=print):
        """paras: list text các đoạn theo thứ tự sách. Bỏ qua đoạn ngắn (tiêu đề, tên...)."""
        import time
        cache = dict(cache or {})
        todo = [k for k, t in enumerate(paras) if len(t) >= min_chars and _h(t) not in cache]
        prompts = {k: self.prompt(paras, k) for k in todo}
        todo.sort(key=lambda k: len(prompts[k]))   # gom đoạn dài gần nhau cho đỡ đệm
        t0 = time.time()
        if todo:
            log(f"Chấm điểm {len(todo)} đoạn...")
        for n in range(0, len(todo), self.batch):
            ks = todo[n:n + self.batch]
            for k, pr in zip(ks, self._probs([prompts[k] for k in ks])):
                cache[_h(paras[k])] = [round(x, 4) for x in pr]
            if save:
                save(cache)
            if (n // self.batch) % 10 == 9 or n + self.batch >= len(todo):
                log(f"  {min(n + self.batch, len(todo))}/{len(todo)} đoạn, {time.time() - t0:.0f}s")
        return cache

    def close(self):
        import gc
        import torch
        self.model = None
        gc.collect()
        torch.cuda.empty_cache()


def decide(probs, threshold):
    """Sắc thái cảm xúc mạnh nhất nếu xác suất của nó >= threshold, không thì kể chuyện."""
    if not probs:
        return DEFAULT
    best = max(range(1, len(EMOTIONS)), key=lambda j: probs[j])
    return EMOTIONS[best] if probs[best] >= threshold else DEFAULT


def paragraphs(units):
    """Text từng đoạn theo thứ tự p (0..max)."""
    out = {}
    for u in units:
        out[u["p"]] = (out.get(u["p"], "") + " " + u["text"]).strip()
    return [out.get(p, "") for p in range(max(out) + 1)] if out else []


def threshold_table(units, scores, thresholds=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)):
    """Với mỗi ngưỡng: bao nhiêu % câu sẽ có sắc thái cảm xúc. Dùng để chọn NGUONG."""
    paras = paragraphs(units)
    probs = [scores.get(_h(t)) for t in paras]
    rows = []
    for th in thresholds:
        n = sum(decide(probs[u["p"]], th) != DEFAULT for u in units)
        rows.append((th, n, 100 * n / max(len(units), 1)))
    return rows


# --------------------------------------------------------------------------
# Hàm chính
# --------------------------------------------------------------------------
def assign(units, clips, cache=None, overrides=None, tagger=None, save=None, log=print):
    """Gán u['reg'], u['voice'], u['speed'], u['key'] cho từng unit (sửa tại chỗ).

    cache: dict {hash của say: sắc thái} đọc/ghi lại tags.json. Trả về cache đã cập nhật.
    save:  hàm save(cache), gọi sau mỗi lô Claude trả về (ngắt giữa chừng không mất nhãn).
    """
    cache = dict(cache or {})
    overrides = overrides or {}
    todo = [u for u in units if u["i"] not in overrides and u["hash"] not in cache]
    if todo and tagger is not None:
        para_text = {}
        for u in units:
            para_text[u["p"]] = (para_text.get(u["p"], "") + " " + u["text"]).strip()
        hash_of = {u["i"]: u["hash"] for u in todo}

        def on_batch(got):
            cache.update({hash_of[i]: r for i, r in got.items()})
            if save:
                save(cache)

        log(f"Gán sắc thái cho {len(todo)} câu "
            f"(~{sum(len(u['text']) for u in todo) / 1000:.0f}k ký tự)...")
        tagger.tag(todo, para_text, on_batch=on_batch, log=log)
    for u in units:
        reg = overrides.get(u["i"]) or cache.get(u["hash"])
        if reg not in REGISTERS:
            reg = heuristic(u["text"]) or DEFAULT
        u["reg"] = reg
        u["voice"] = resolve(reg, clips)
        u["speed"] = REGISTERS[reg]["speed"]
        u["key"] = unit_key(u["say"], u["voice"], u["speed"])
    return cache


def assign_scored(units, clips, scores, threshold, overrides=None):
    """Như assign(), nhưng sắc thái lấy từ điểm theo đoạn (LocalScorer).

    Ưu tiên: OVERRIDES > cảm xúc của cả đoạn (nếu vượt ngưỡng) > lời thoại (luật) > kể chuyện.
    """
    overrides = overrides or {}
    paras = paragraphs(units)
    para_reg = [decide(scores.get(_h(t)), threshold) for t in paras]
    for u in units:
        reg = overrides.get(u["i"])
        if reg not in REGISTERS:
            reg = para_reg[u["p"]]
            if reg == DEFAULT:
                reg = heuristic(u["text"]) or DEFAULT
        u["reg"] = reg
        u["voice"] = resolve(reg, clips)
        u["speed"] = REGISTERS[reg]["speed"]
        u["key"] = unit_key(u["say"], u["voice"], u["speed"])

