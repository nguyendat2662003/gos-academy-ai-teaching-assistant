# GOS Academy AI Teaching Assistant (MVP)

AI trợ giảng trả lời câu hỏi học viên trong nhóm chat (giai đoạn này mô phỏng Zalo qua webhook).
Bot trả lời bằng tiếng Việt dựa trên học liệu đã duyệt của **đúng lớp**, có dẫn nguồn, và chuyển giảng viên khi
không đủ căn cứ.

- Hướng dẫn cài đặt & triển khai (Word, có ảnh chụp từng bước, giải thích từng thành phần):
  [docs/HUONG_DAN_CAI_DAT.docx](docs/HUONG_DAN_CAI_DAT.docx)
- Kiến trúc (sơ đồ Mermaid, luồng dữ liệu, cách ly lớp, vai trò & quyền): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Kiểm thử, kết quả 7 tình huống, đánh giá RAG: [docs/TEST_REPORT.md](docs/TEST_REPORT.md)
  ([SCENARIOS_RESULTS](docs/SCENARIOS_RESULTS.md), [EVAL_RESULTS](docs/EVAL_RESULTS.md))
- Chi phí vận hành & điều kiện tích hợp Zalo thật: [docs/COST_AND_ZALO.md](docs/COST_AND_ZALO.md)
- Quyết định kỹ thuật (D-01…D-89): [docs/DECISIONS.md](docs/DECISIONS.md)

> Trạng thái: **hoàn thành MVP**. 264 test offline xanh; trên stack thật với OpenAI: 7/7 tình
> huống đạt, đánh giá 40 câu golden quyết định đúng 40/40, rò rỉ chéo lớp 0. Tích hợp Zalo thật mới ở mức khung
> (cần quyền OA + GMF).

## Bot xử lý một câu hỏi thế nào

`@Trợ lý …` (hoặc `/hoi …`) → che secret → guard (injection / đòi bí mật / lớp khác → từ chối) → chỉ chào/cảm ơn → chào lại → lịch sử (cùng lớp, có TTL)
→ viết lại câu hỏi nối tiếp → truy xuất hybrid (chỉ lớp đó + COMMON) → chủ đề nhạy cảm không có căn cứ → chuyển
giảng viên → điểm < `RETRIEVAL_MIN_SCORE` → chuyển giảng viên (không gọi LLM) → LLM trả JSON (timeout + retry)
→ kiểm tra (JSON, `answerable`, trích dẫn thuộc tập vừa truy xuất) → ghép câu trả lời + nguồn từ metadata.

| Outcome | Khi nào | Học viên nhận |
|---|---|---|
| `answered` | đủ căn cứ | câu trả lời + `📚 Nguồn: …` |
| `partial` | chỉ một phần có căn cứ | phần trả lời được + "Phần “X” chưa có trong tài liệu…" + mã `#H-…` |
| `handoff` | `no_context`, `low_confidence`, `policy` | thông báo đã chuyển giảng viên + mã `#H-…` |
| `refused` | injection, đòi bí mật, đòi dữ liệu lớp khác | từ chối lịch sự (+ `security_events`) |
| `smalltalk` | tin chỉ có lời chào / cảm ơn (`@Trợ lý chào bạn`) | câu chào cố định + cách hỏi; không gọi LLM, không tạo ticket (D-87) |
| `error` | LLM lỗi sau khi đã retry | xin lỗi + mã `#H-…` (ticket `error`) |

Mọi câu chữ gửi học viên nằm ở [app/agent/messages.py](app/agent/messages.py); prompt nằm ở
[app/agent/prompts.py](app/agent/prompts.py).

## Yêu cầu

> Lần đầu cài đặt: xem **[hướng dẫn cài đặt & triển khai](docs/HUONG_DAN_CAI_DAT.docx)** (Word, có ảnh chụp
> từng bước, giải thích từng thành phần, triển khai lên máy chủ và xử lý sự cố). Phần dưới đây là bản tóm tắt.

- Docker Desktop (có `docker compose`)
- Python 3.11 (chỉ cần nếu chạy test/script từ máy host)

## Chạy nhanh

```powershell
# 1. Tạo file cấu hình (KHÔNG commit .env)
Copy-Item .env.example .env      # bash: cp .env.example .env
#    -> sửa các giá trị change-me thành chuỗi ngẫu nhiên; điền OPENAI_API_KEY (xem "Kho tri thức")

# 2. Khởi động toàn bộ stack (postgres+pgvector, redis, migrate, api, worker)
docker compose up -d --build

# 3. Kiểm tra
curl http://127.0.0.1:8000/health
# {"status":"ok","checks":{"db":"ok","redis":"ok"}}
```

Service one-shot `migrate` tự chạy mỗi lần `up`: migration, đồng bộ `config/classes.yaml`, rồi **ingest
`data/samples`** (D-82). Nội dung không đổi được bỏ qua theo hash, nên chỉ lần đầu mới gọi API embedding. Nếu ingest
lỗi (thường do key/model embedding sai trong `.env`) thì `migrate` thoát với lỗi và api/worker không khởi động:
xem `docker compose logs migrate`, sửa `.env` rồi `docker compose up -d`.
Thay đổi làm trên trang quản trị được giữ: file mẫu đã bị thay bằng bản tải lên (cùng tên file hoặc cùng mã tài liệu)
hoặc đã bị xóa ở đó thì `migrate` bỏ qua (dòng `kept` trong log), không nạp lại bản cũ. Muốn quay về học liệu mẫu:
`docker compose exec api python scripts/ingest_samples.py --restore-samples`.
Chạy lại thủ công nếu cần:

```powershell
docker compose run --rm migrate
# hoặc từng bước:
docker compose exec api alembic upgrade head
docker compose exec api python -m app.db.seed
docker compose exec api python scripts/ingest_samples.py
```

## Kho tri thức

### Cấu hình model (OpenAI)

Tự điền trong `.env` (không dán key vào chat, không commit):

```
LLM_PROVIDER=openai
LLM_MODEL=gpt-6-luna            # hoặc gpt-5.6-luna
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=768               # giữ 768: model được gọi với dimensions=768
OPENAI_API_KEY=...
```

Sau khi sửa `.env`: `docker compose up -d` (container đọc lại biến môi trường; `migrate` tự ingest lại). Đổi model
embedding thì mọi tài liệu tự được embed lại (D-38).

### Ingest học liệu mẫu

`docker compose up` đã tự ingest (xem trên). Chạy tay khi cần:

```powershell
docker compose exec api python scripts/ingest_samples.py          # data/samples/<SCOPE>/*
docker compose exec api python scripts/ingest_samples.py --force  # embed lại kể cả nội dung không đổi
```

Tên thư mục là phạm vi: `GS-KPI-01`, `AUTO-N8N-01`, hoặc `COMMON` (file trộn nhiều lớp, tách theo tiền tố mã mục
khai báo ở `section_prefixes` trong `config/classes.yaml`). Thư mục bắt đầu bằng `_` bị bỏ qua.
Kết quả mong đợi: GS-KPI-01 = 13 chunk, AUTO-N8N-01 = 15 chunk, COMMON = 4 chunk.

### Xem trước parse/chunk (không cần DB, không gọi API)

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python scripts/preview_chunks.py --first 5
.\.venv\Scripts\python scripts/derive_samples.py   # sinh lại data/derived/ (cần Word hoặc LibreOffice)
```

### Tài liệu: trang quản trị và API (header `X-Admin-Key`)

Trên **http://127.0.0.1:8000/admin/ui**, mục "Tài liệu học liệu" (hoặc nút tài liệu ở thanh trái của `/demo`):
chọn file + lớp → **Tải lên & nạp**, trang báo kết quả từng phạm vi (phiên bản mới, không đổi, file bị thay, số FAQ cần
xem lại, lỗi 422 kèm lý do). Danh sách lọc theo lớp và trạng thái; **Đánh lại chỉ mục** và **Xóa** (bấm hai lần) chỉ
hiện với tài liệu mà khóa đang dùng được sửa. Giảng viên chỉ tải lên cho lớp mình và xem thêm tài liệu chung COMMON.

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/admin/documents?class_id=&status=active` | `status=` rỗng = mọi trạng thái |
| POST | `/admin/documents` | multipart `file` + `class_id` (hoặc `COMMON`); PDF/DOCX/XLSX ≤ `MAX_UPLOAD_MB` |
| DELETE | `/admin/documents/{id}` | soft delete + xóa chunk |
| POST | `/admin/documents/{id}/reindex` | parse lại bản gốc + embed lại → version mới |

Quy tắc:
- Nội dung không đổi → `unchanged`, không tốn token.
- Nội dung đổi → version mới, chỉ chuyển `active` sau khi embed xong. Version cũ chuyển `superseded` và chunk cũ bị
  xóa trong cùng transaction.
- "Version cũ" là tài liệu đang `active` cùng phạm vi có **cùng tên file hoặc cùng mã tài liệu** (`Mã tài liệu:
  DOC-GS-01`): đổi tên file vẫn thay đúng bản cũ, kết quả ghi tên file bị thay ở `replaced` (D-88). Mã tài liệu đã
  thuộc một nguồn khác trong cùng lớp → `422`.
- Nội dung của một lớp đổi (phiên bản mới, bị xóa) → các FAQ đã duyệt của lớp đó được đánh dấu **cần xem lại**;
  đổi tài liệu COMMON thì đánh dấu FAQ của mọi lớp (D-89, xem "FAQ đã duyệt" bên dưới).
- File tải lên cho một lớp mà chứa mục của lớp khác → `422`, không ghi gì vào DB.

## Gửi tin nhắn mô phỏng

Script tự ký HMAC bằng `WEBHOOK_SECRET` đọc từ `.env` (không in ra màn hình).

> Dùng **Git Bash** trên Windows: đặt `export MSYS_NO_PATHCONV=1` trước khi chạy. Nếu không, Git Bash tự đổi
> `"/hoi …"` thành `"C:/Program Files/Git/hoi …"` và tin nhắn sẽ bị bỏ qua (`no_trigger`). PowerShell không bị.

```powershell
$py = ".\.venv\Scripts\python.exe"
# Một câu hỏi
& $py scripts/send_mock_event.py --group grp_auto_n8n_01 --user hv01 --text "/hoi Em bị lỗi 401 trong n8n"
# Gửi cùng event 2 lần đồng thời -> một "queued", một "duplicate"
& $py scripts/send_mock_event.py --group grp_gs_kpi_01 --user hv02 --text "/hoi SUMIFS lỗi?" --duplicate
# Tin của bot / không có trigger -> "ignored"
& $py scripts/send_mock_event.py --group grp_gs_kpi_01 --text "/hoi test" --bot
# Phát lại 8 tin mẫu (class_id trong file được đổi thành group_id; đổi --event-prefix để chạy lại)
& $py scripts/send_mock_event.py --replay data/samples/_meta/Tin_nhan_mo_phong_TTS.json --event-prefix run1-

# Xem tin bot đã "gửi"
docker compose exec postgres psql -U gos -d gos -c "select event_id, external_group_id, kind, text from outbox order by id"
```

Bật/tắt bot theo lớp:

```powershell
curl.exe -X POST http://127.0.0.1:8000/admin/classes/AUTO-N8N-01/toggle `
  -H "X-Admin-Key: <ADMIN_API_KEY>" -H "Content-Type: application/json" -d '{\"enabled\": false}'
```

### Webhook mô phỏng

`POST /webhooks/mock`, header `X-Timestamp` (unix giây, lệch tối đa 300 s) và
`X-Signature = hex(HMAC_SHA256(WEBHOOK_SECRET, "{X-Timestamp}.{raw_body}"))`.

| Kết quả | Khi nào |
|---|---|
| `401` | thiếu header, sai chữ ký, timestamp lệch > 300 s (ghi `security_events`) |
| `200 duplicate` | `event_id` đã nhận (kể cả gửi đồng thời) |
| `200 ignored` | tin của bot, không bắt đầu bằng `@Trợ lý` hoặc `/hoi`, câu hỏi rỗng, nhóm không thuộc lớp nào, lớp đang tắt bot, loại event khác |
| `200 rate_limited` | vượt `RATE_LIMIT_USER_PER_MIN` / `RATE_LIMIT_CLASS_PER_MIN` (thông báo 1 lần/phút) |
| `200 queued` | đã đưa vào hàng đợi worker |

`POST /webhooks/zalo` trả `501` — xem [app/channels/zalo.py](app/channels/zalo.py) về điều kiện tích hợp Zalo OA/GMF.

## Giảng viên: ticket & FAQ

Trang **http://127.0.0.1:8000/admin/ui** → nhập khóa truy cập (lưu trong sessionStorage của tab, không nằm
trong mã trang) → lọc ticket theo lớp/trạng thái → chọn ticket → nhập câu trả lời → tick "Gửi câu trả lời vào
nhóm" → **Lưu** → **Duyệt vào FAQ của lớp** (có thể viết lại câu hỏi cho tổng quát). FAQ được index ngay, chỉ
cho lớp của ticket; câu hỏi tương tự lần sau bot trả lời với nguồn `FAQ đã duyệt (FAQ giảng viên #N)`.

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/admin/classes` | lớp + trạng thái bot (không trả liên hệ giảng viên) |
| GET | `/admin/handoffs?class_id=&status=&limit=` | mới nhất trước |
| GET | `/admin/handoffs/{id}` | |
| PATCH | `/admin/handoffs/{id}` | `{status?, assignee?, instructor_answer?, post_to_group?}`; câu trả lời được che secret; có câu trả lời mà không nêu status → `answered` |
| POST | `/admin/handoffs/{id}/promote` | `{question?, answer?, approved_by?}`; `409` nếu chưa có câu trả lời hoặc đã duyệt |
| GET | `/admin/handoffs/export.csv?class_id=&status=` | UTF-8 BOM (mở thẳng bằng Excel/Google Sheets), chặn công thức `= + - @` |

Ticket tạo từ `/api/ask` không có nhóm chat nên không gửi vào nhóm được (`409`).

### FAQ đã duyệt: xem lại khi tài liệu đổi (D-89)

Khi tài liệu của một lớp có phiên bản mới (nội dung thật sự đổi) hoặc bị xóa, mọi FAQ đang dùng của lớp đó được đánh
dấu **cần xem lại** kèm lý do (ví dụ "Tài liệu DOC-GS-01 (…docx) vừa có phiên bản v4"). Bot **vẫn dùng** FAQ cho đến
khi giảng viên quyết định, trên mục "FAQ đã duyệt" của `/admin/ui`: **Vẫn đúng**, **Sửa** (embed lại ngay, câu cũ không
còn được truy xuất) hoặc **Tắt** (bot không dùng nữa; **Bật lại** được).

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/admin/faqs?class_id=&status=review\|active\|inactive` | FAQ cần xem lại đứng đầu |
| PATCH | `/admin/faqs/{id}` | `{question?, answer?, active?, reviewed?}`; mọi thay đổi (kể cả `reviewed: true`) xóa cờ cần xem lại; sửa nội dung thì người duyệt = khóa đang dùng |

### Khóa giảng viên theo lớp (D-83)

Mỗi lớp có một khóa riêng cho giảng viên, khai trong `.env` (mỗi khóa ≥ 16 ký tự, khác nhau và khác
`ADMIN_API_KEY`; sinh bằng `python -c "import secrets;print(secrets.token_urlsafe(24))"`):

```
INSTRUCTOR_API_KEYS=GS-KPI-01=<khóa GS>,AUTO-N8N-01=<khóa AUTO>
```

Rồi `docker compose up -d` (api đọc lại `.env`; sai mã lớp thì api không khởi động). Nhập khóa giảng viên vào cùng ô
"Khóa truy cập" của `/admin/ui`: trang hiện "Giảng viên · GS-KPI-01", chỉ còn ticket, tài liệu, thống kê của lớp đó.
`GET /admin/me` cho biết khóa đang dùng thuộc vai trò nào. Bảng quyền đầy đủ: [docs/ARCHITECTURE.md §4](docs/ARCHITECTURE.md).

| Thao tác | Quản trị | Giảng viên |
|---|---|---|
| Ticket, trả lời, gửi nhóm, duyệt FAQ | mọi lớp | lớp mình (lớp khác → 404) |
| FAQ đã duyệt: xem, xác nhận, sửa, tắt/bật | mọi lớp | lớp mình (lớp khác → 404) |
| Tài liệu: xem | mọi lớp | lớp mình + COMMON |
| Tài liệu: tải lên / xóa / đánh lại chỉ mục | mọi lớp | chỉ tài liệu riêng của lớp mình |
| Thống kê `/admin/stats` | mọi lớp | lớp mình |
| Bật/tắt bot, sự kiện bảo mật, `/demo` | ✓ | 403 |

## Demo nhóm chat (quay video)

Chỉ bật khi `APP_ENV=dev`. Mở **http://127.0.0.1:8000/demo** → nhập `ADMIN_API_KEY` (khóa giảng viên không mở
được demo). Giao diện mô phỏng một ứng dụng chat nhóm (D-84), ghi rõ là **mô phỏng**:

- **Hỏi bot bằng cách nhắc tên**: gõ `@` → chọn **Trợ lý** trong danh sách thành viên (như nhắc tên trong ứng
  dụng chat), rồi gõ câu hỏi: `@Trợ lý Bài tập nộp khi nào?`. Nhắc tên phải ở đầu tin; nhắc một học viên khác
  hoặc tin không nhắc bot thì bot bỏ qua. Lệnh `/hoi` vẫn dùng được (D-86).
- **Danh sách hội thoại** bên trái: mỗi nhóm trong `classes.yaml` là một hội thoại, có tin cuối và số tin chưa đọc.
- **Khung chat**: bong bóng tin, tin của bot trích dẫn tin được trả lời, phần `📚 Nguồn` tách riêng, nhãn loại
  phản hồi (trả lời có nguồn / chuyển giảng viên / từ chối…), trạng thái "Đã nhận" hoặc lý do bot bỏ qua.
  "Gửi với tư cách" chọn học viên An/Bình/Chi, hoặc *một tài khoản bot khác* để thấy bot không trả lời bot.
  Nút **Câu hỏi mẫu** chứa câu cho 7 tình huống.
- **Khung "Sự kiện webhook"** bên phải: mỗi tin là một `POST /webhooks/mock` với header `X-Timestamp`, payload
  JSON và phản hồi (`queued`, `ignored · no_trigger`, `duplicate`, `rate_limited`…); chữ ký HMAC do server tạo và
  không bao giờ hiện ra. Mỗi sự kiện có nút **Gửi lại y hệt** và **Gửi 2 lần đồng thời** (tình huống 6: luôn chỉ
  một lần được xử lý). Tin bot gửi ra (`adapter.send_reply` → outbox) cũng hiện ở đây.

Câu trả lời đọc lại từ outbox mỗi 1,5 giây, kể cả tin giảng viên gửi từ trang admin. Cần worker đang chạy.

Kịch bản gợi ý: hỏi cùng "Bài tập nộp khi nào?" ở 2 nhóm → hỏi câu ngoài giáo trình → sang `/admin/ui` trả lời +
gửi nhóm + duyệt FAQ → hỏi lại câu đó ở nhóm cũ (trả lời từ FAQ) và ở nhóm kia (vẫn chuyển giảng viên).

## Thống kê & chi phí

Trên `/admin/ui` (mục "Thống kê & chi phí ước tính") hoặc gọi API:

```powershell
curl.exe -H "X-Admin-Key: <ADMIN_API_KEY>" "http://127.0.0.1:8000/admin/stats?class_id=GS-KPI-01&from=2026-11-01&to=2026-11-30"
curl.exe -H "X-Admin-Key: <ADMIN_API_KEY>" "http://127.0.0.1:8000/admin/security-events?type=prompt_injection&limit=50"
```

- `total` / `by_class` / `by_day` (ngày theo giờ Việt Nam): số câu hỏi bot xử lý, `answered`, `partial`, `handoff`,
  `refused`, `error`, `ignored`, `duplicate`, `rate_limited`, `tickets_by_reason`, latency TB/p95 (từ lúc nhận
  webhook đến lúc gửi trả lời), token vào/ra/embedding, `cost_usd`.
- `ingest`: token embedding khi index tài liệu (mọi version) và khi duyệt FAQ.
- **Chi phí = token thực tế × đơn giá trong [config/pricing.yaml](config/pricing.yaml)**, tính lúc xem, nên điền giá
  sau vẫn ra chi phí của lịch sử. Repo chỉ có placeholder `null` → `cost_usd: null` và
  `pricing.models_missing_price` liệt kê model chưa có giá. Điền đơn giá (USD / 1 triệu token) từ trang giá chính
  thức (`checked_at` tùy chọn), rồi `docker compose up -d --force-recreate api worker`.

## Đánh giá & kịch bản (stack thật)

```powershell
# 7 tình huống bắt buộc qua webhook thật → bảng kết quả (exit code 1 nếu có kiểm tra không đạt)
docker compose exec api python scripts/run_scenarios.py --out /tmp/scn.md

# đánh giá RAG trên data/eval/golden.yaml: hit@k, MRR, rò rỉ chéo lớp, quét ngưỡng
docker compose exec api python scripts/eval_rag.py
# + pipeline đầy đủ với LLM thật (chạy trong 1 transaction rồi rollback: không để lại ticket/log)
docker compose exec api python scripts/eval_rag.py --full --min-score 0.35 --out /tmp/eval.md
docker compose cp api:/tmp/eval.md docs/EVAL_RESULTS.md
```

`RETRIEVAL_MIN_SCORE=0.35` được hiệu chỉnh bằng lệnh trên (D-74). Đổi học liệu hoặc model embedding thì chạy lại.

## Chạy test

Test chạy offline (provider `fake`), dùng DB riêng `gos_test`, được tạo lại mỗi lần chạy (không đụng DB chính).

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
docker compose up -d postgres redis
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\ruff check .
```

## Cấu trúc

```
app/core/      config (env), logging JSON, security helpers, classes registry, redis, pricing (pricing.yaml)
app/db/        models SQLAlchemy, session, seed classes.yaml, stats (tổng hợp cho /admin/stats)
app/api/       routers: /health, /webhooks/{mock,zalo}, /api/ask, /admin/{me,classes,documents,faqs,handoffs,stats,security-events}, /admin/ui, /demo
app/channels/  ChannelAdapter, MockWebhookAdapter (HMAC + outbox), ZaloGMFAdapter (stub), ingress (dedupe → lọc → rate limit → enqueue)
app/agent/     pipeline (điều phối), guard, policy, prompts, verify, sources, conversation, handoff, messages
app/ingestion/ parsers (DOCX/PDF/XLSX), chunker, luật flag injection, indexer (phân lớp, versioning), faq (duyệt ticket → FAQ)
app/templates/ Jinja2: base, admin, demo (CSP nonce, dữ liệu chèn bằng textContent)
app/providers/ embedding + LLM: openai, gemini, fake; retry (timeout + backoff)
app/retrieval/  hybrid_search (vector + full-text IDF, RRF) — bắt buộc class_id
app/workers/   arq worker: process_message, send_notice
scripts/       send_mock_event, ingest_samples, preview_chunks, derive_samples, run_scenarios, eval_rag
alembic/       migration 0001 (extension vector + toàn bộ bảng), 0002 (documents: origin_scope, storage_path), 0003 (model embedding + token FAQ), 0004 (FAQ cần xem lại, index mã tài liệu)
config/        classes.yaml (lớp ↔ nhóm chat ↔ tiền tố mã mục), pricing.yaml (đơn giá token — tự điền)
data/samples/  học liệu mẫu theo lớp (KHÔNG sửa); _meta/ = tài liệu hướng dẫn + tin nhắn mô phỏng (không ingest)
data/derived/  bản PDF/XLSX chuyển từ samples (không đổi nội dung, không ingest mặc định)
data/eval/     golden.yaml (40 câu đánh giá: lớp, kỳ vọng, mục chứa đáp án)
docs/          ARCHITECTURE, TEST_REPORT, COST_AND_ZALO, DECISIONS, kết quả chạy thật (SCENARIOS/EVAL_RESULTS)
tests/         pytest (gồm test_security_audit: kiểm chứng 4 ràng buộc cứng)
```

## Lớp học

| class_id | Tên | group_id mô phỏng |
|---|---|---|
| `GS-KPI-01` | Google Sheets – KPI – Dashboard | `grp_gs_kpi_01` |
| `AUTO-N8N-01` | AI Automation – n8n | `grp_auto_n8n_01` |
| `COMMON` | Quy định & FAQ chung (dùng chung, không có nhóm) | — |

`class_id` luôn được server suy ra từ `(channel, group_id)`, không bao giờ lấy từ nội dung tin nhắn.

## Đổi model embedding

`EMBEDDING_DIM` phải khớp số chiều cột `chunks.embedding` (tạo ở migration 0001, hiện là 768).
- Đổi model nhưng giữ 768 chiều (ví dụ OpenAI `text-embedding-3-*` với `dimensions`): chỉ cần chạy lại
  `scripts/ingest_samples.py`. Hash có chứa tên model nên mọi tài liệu được embed lại.
- Đổi sang số chiều khác: tạo migration mới đổi kiểu cột (xóa và tạo lại index HNSW), rồi ingest lại toàn bộ.

## Bảo mật

- Mọi secret đọc từ biến môi trường; `.env` bị chặn bởi `.gitignore` và `.dockerignore`.
- Postgres/Redis chỉ mở cổng trên `127.0.0.1`.
- `/health` chỉ trả trạng thái, không trả cấu hình.
