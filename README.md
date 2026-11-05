# GOS Academy AI Teaching Assistant (MVP)

AI trợ giảng trả lời câu hỏi học viên trong nhóm chat (giai đoạn này mô phỏng Zalo qua webhook).
Bot trả lời bằng tiếng Việt dựa trên học liệu đã duyệt của **đúng lớp**, có dẫn nguồn, và chuyển giảng viên khi
không đủ căn cứ.

- Đặc tả: [CLAUDE.md](CLAUDE.md) · Đề bài: `docs/de_bai.pdf` (không đưa lên repo; đặt file vào đường dẫn này khi cần)
- Quyết định kỹ thuật: [docs/DECISIONS.md](docs/DECISIONS.md)

> Trạng thái: **Phase 3 (kho tri thức)** — webhook mô phỏng (Phase 2) + parse DOCX/PDF/XLSX, chunk theo mục,
> embedding (openai/gemini/fake), index có versioning, API quản lý tài liệu. Worker vẫn trả lời "echo";
> truy xuất & agent ở Phase 4.

## Yêu cầu

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

Migration và đồng bộ `config/classes.yaml` chạy tự động bởi service one-shot `migrate`.
Chạy lại thủ công nếu cần:

```powershell
docker compose run --rm migrate
# hoặc từng bước:
docker compose exec api alembic upgrade head
docker compose exec api python -m app.db.seed
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

Sau khi sửa `.env`: `docker compose up -d` (container đọc lại biến môi trường) rồi ingest lại. Đổi model embedding
thì mọi tài liệu tự được embed lại (D-38).

### Ingest học liệu mẫu

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

### API tài liệu (header `X-Admin-Key`)

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
- File tải lên cho một lớp mà chứa mục của lớp khác → `422`, không ghi gì vào DB.

## Gửi tin nhắn mô phỏng

Script tự ký HMAC bằng `WEBHOOK_SECRET` đọc từ `.env` (không in ra màn hình).

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
| `200 ignored` | tin của bot, không bắt đầu bằng `/hoi`, câu hỏi rỗng, nhóm không thuộc lớp nào, lớp đang tắt bot, loại event khác |
| `200 rate_limited` | vượt `RATE_LIMIT_USER_PER_MIN` / `RATE_LIMIT_CLASS_PER_MIN` (thông báo 1 lần/phút) |
| `200 queued` | đã đưa vào hàng đợi worker |

`POST /webhooks/zalo` trả `501` — xem [app/channels/zalo.py](app/channels/zalo.py) về điều kiện tích hợp Zalo OA/GMF.

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
app/core/      config (env), logging JSON, security helpers, classes registry, redis
app/db/        models SQLAlchemy, session, seed classes.yaml
app/api/       routers: /health, /webhooks/{mock,zalo}, /admin/classes/{id}/toggle, /admin/documents
app/channels/  ChannelAdapter, MockWebhookAdapter (HMAC + outbox), ZaloGMFAdapter (stub), ingress (dedupe → lọc → rate limit → enqueue)
app/agent/     messages.py (mọi câu chữ gửi học viên)
app/ingestion/ parsers (DOCX/PDF/XLSX), chunker, luật flag injection, indexer (phân lớp, versioning)
app/providers/ embedding: openai, gemini, fake
app/workers/   arq worker: process_message, send_notice
scripts/       send_mock_event, ingest_samples, preview_chunks, derive_samples
alembic/       migration 0001 (extension vector + toàn bộ bảng), 0002 (documents: origin_scope, storage_path)
config/        classes.yaml (lớp ↔ nhóm chat ↔ tiền tố mã mục), pricing.yaml (đơn giá token — tự điền)
data/samples/  học liệu mẫu theo lớp (KHÔNG sửa); _meta/ = tài liệu hướng dẫn + tin nhắn mô phỏng (không ingest)
data/derived/  bản PDF/XLSX chuyển từ samples (không đổi nội dung, không ingest mặc định)
tests/         pytest
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
