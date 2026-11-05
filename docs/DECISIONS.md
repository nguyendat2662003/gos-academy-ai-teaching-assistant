# Nhật ký quyết định kỹ thuật (ADR rút gọn)

Mỗi mục: **Bối cảnh → Quyết định → Phương án loại → Lý do**. Mã `D-xx` được tham chiếu trong code/comment.

---

## Phase 0 — Khảo sát học liệu & đề bài

### D-01. Kho dùng chung `COMMON` bên cạnh kho từng lớp
- **Bối cảnh:** Học liệu (`00_Huong_dan...`, M-02) yêu cầu "FAQ chung được truy xuất cho cả hai lớp". CLAUDE.md lại quy định mỗi tài liệu gắn đúng một lớp.
- **Quyết định:** Thêm phạm vi `COMMON` (một dòng trong bảng `classes` với `is_shared = true`, không có nhóm chat). Truy xuất luôn lọc `class_id IN (:class_id, 'COMMON')`. `class_id` vẫn là tham số bắt buộc, vẫn suy ra từ `group_id`.
- **Phương án loại:** (a) Copy chunk COMMON vào từng lớp: dữ liệu trùng, cập nhật dễ lệch nhau. (b) Bỏ COMMON, gán FAQ chung cho một lớp: sai yêu cầu đề.
- **Lý do:** Vẫn đảm bảo không lớp nào thấy dữ liệu chuyên môn của lớp khác. COMMON chỉ chứa quy định chung, đã được đánh dấu rõ trong tài liệu nguồn.

### D-02. Một file chứa nhiều phạm vi → tách thành nhiều bản ghi `documents`
- **Bối cảnh:** `03_FAQ_Quy_dinh_lop_hoc_GIA_LAP.docx` chứa cả mục `COMMON-*`, `GS-*`, `AUTO-*`.
- **Quyết định:** Lớp của từng mục được xác định tất định theo tiền tố mã mục: `COMMON-` → COMMON, `GS-` → GS-KPI-01, `AUTO-` → AUTO-N8N-01. Khi ingest, file được tách thành một bản ghi `documents` cho mỗi phạm vi, nên bất biến "mỗi document thuộc đúng một lớp" vẫn giữ nguyên.
- **Phương án loại:** Để LLM phân loại mục: không tất định và vi phạm nguyên tắc "class_id không bao giờ đến từ LLM".
- **Lý do:** Dễ giải thích, dễ test, không phụ thuộc mô hình.

### D-03. Trích dẫn theo "mã tài liệu + mã mục"
- **Bối cảnh:** Học liệu M-02 yêu cầu trích dẫn kiểu `GS-02`, `AUTO-03`. Các DOCX không có số trang ổn định.
- **Quyết định:** Phần nguồn do code ghép từ metadata: `📚 Nguồn: DOC-GS-01 – GS-02 (01_Giao_trinh_...docx)`. Với PDF dùng `trang N`, với XLSX dùng `Sheet X, dòng N`.
- **Lý do:** LLM không bao giờ tự viết tên nguồn, nên không thể bịa nguồn.

### D-04. Tình huống 1 ("RAG khác Fine-tuning") → outcome `partial`
- **Bối cảnh:** Đề kỳ vọng "giải thích ngắn gọn, đúng học liệu, dẫn nguồn". Học liệu (AUTO-05) chỉ định nghĩa RAG, không nói gì về fine-tuning.
- **Quyết định:** Thêm outcome `partial`: bot trả lời phần có căn cứ (RAG, kèm nguồn), nói rõ phần "Fine-tuning" chưa có trong giáo trình, đồng thời tạo ticket với lý do `partial_coverage` cho giảng viên. Cơ chế: JSON đầu ra của LLM có thêm trường `unanswered_parts`; khác rỗng → `partial`.
- **Phương án loại:** (b) Handoff toàn bộ: an toàn nhưng bỏ phí phần có căn cứ. (c) Trả lời bằng kiến thức chung của LLM: vi phạm ràng buộc cứng #3.
- **Lý do:** Đúng tinh thần đề bài là "chỉ khẳng định khi có nguồn; nếu không đủ căn cứ phải nói rõ chưa xác minh được".

### D-05. Chủ đề chính sách/nhạy cảm mặc định handoff
- **Bối cảnh:** COMMON-03 nói rõ không có dữ liệu học phí/giảm giá/hoàn phí/chứng chỉ. Truy xuất sẽ khớp mục này, và nếu chỉ dựa vào "có truy xuất được tài liệu chính sách" thì bot sẽ coi là có căn cứ.
- **Quyết định:** Câu hỏi thuộc chủ đề nhạy cảm → handoff `policy`, trừ khi truy xuất được một chunk chính sách có nội dung cụ thể (được đánh dấu là tài liệu chính sách thực sự). Với bộ mẫu hiện tại thì luôn là handoff.

### D-06. File tin nhắn mô phỏng không được dùng `class_id` của client
- **Bối cảnh:** `Tin_nhan_mo_phong_TTS.json` gửi kèm `class_id`, và timestamp nằm trong tương lai.
- **Quyết định:** `scripts/send_mock_event.py --replay` dịch `class_id` → `group_id` theo `classes.yaml`, ký HMAC với timestamp hiện tại. Server chỉ tin `group_id`.

### D-07. Không ingest `00_Huong_dan...docx` và file JSON
- Chúng là hướng dẫn cho TTS và dữ liệu kiểm thử, không phải học liệu. Hai file được đặt trong `data/samples/_meta/`; script ingest bỏ qua mọi thư mục bắt đầu bằng `_`.

### D-08. PDF/XLSX: tạo bản chuyển đổi định dạng trong `data/derived/`
- **Bối cảnh:** Đề bắt buộc nhập được PDF, DOCX và XLSX/FAQ, nhưng bộ mẫu chỉ có DOCX.
- **Quyết định:** Script (commit kèm) chuyển giáo trình n8n sang PDF và 2 bảng FAQ sang XLSX trong `data/derived/`. Nội dung không đổi một chữ nào; `data/samples/` giữ nguyên. Việc này làm ở Phase 3.

### D-09. Chunking theo mục
- Mỗi mục trong học liệu chỉ khoảng 60–150 token, nên mỗi mục là một chunk (mỗi dòng bảng FAQ là một chunk). Chỉ cắt nhỏ khi mục vượt khoảng 800 token (overlap khoảng 10–15%). Mỗi chunk kèm tên tài liệu và mã mục.

### D-10. Luật flag injection trong tài liệu chỉ bắt câu mệnh lệnh
- Cụm "API key" xuất hiện hợp lệ trong AUTO-03, AUTO-04 và COMMON-02. Vì vậy chỉ flag các mẫu dạng chỉ dẫn ("ignore previous instructions", "bỏ qua hướng dẫn", "tiết lộ system prompt"...), không flag theo từ khóa đơn lẻ.

### D-11. Câu hỏi mơ hồ → gộp vào `low_confidence`
- Đề III.4 nhắc tới "mơ hồ". Không thêm lý do riêng, vì cơ chế xử lý giống `low_confidence` (LLM trả `answerable=false` hoặc trích dẫn không hợp lệ).

---

## Phase 1 — Nền tảng

### D-12. Thư viện bổ sung ngoài danh sách CLAUDE.md
Mỗi thư viện là phụ thuộc trực tiếp của một thành phần đã chọn:

| Thư viện | Lý do |
|---|---|
| `asyncpg` | Driver async cho SQLAlchemy + PostgreSQL |
| `pgvector` | Kiểu cột `Vector` cho SQLAlchemy |
| `redis` | Client Redis (rate limit, health); arq cũng dùng |
| `pydantic-settings` | Đọc cấu hình từ biến môi trường, secret dạng `SecretStr` |
| `pyyaml` | Đọc `config/classes.yaml`, `config/pricing.yaml` |
| `python-multipart` | FastAPI cần để nhận upload multipart |
| `jinja2` | Template admin/demo |
| `google-genai`, `openai` | SDK chính thức của provider |

### D-13. Python 3.11 cố định
`requires-python = ">=3.11,<3.12"`. Docker image dùng `python:3.11-slim`, venv local tạo bằng `py -3.11`. Lý do: máy dev mặc định là 3.14, và một số wheel (asyncpg, pymupdf) có thể chưa ổn định trên 3.14.

### D-14. Trạng thái/outcome lưu bằng `String` + `StrEnum` Python, không dùng ENUM của Postgres
- Thêm giá trị mới (ví dụ `partial`) không cần migration `ALTER TYPE`. Validate ở tầng Python.

### D-15. `tsv` là cột generated (`to_tsvector('simple', content)`), index GIN; `embedding` có index HNSW cosine
- Không cần code để đồng bộ tsv khi sửa content. Dùng `simple` vì Postgres không có stemmer tiếng Việt.

### D-16. Bảng `chunks` có `document_id` HOẶC `faq_entry_id` (CHECK đúng một)
- FAQ do giảng viên duyệt được index ngay, không cần tạo document giả.

### D-17. Chống trùng ở 2 lớp
- `processed_events` có PK `(channel, event_id)`: chặn job trùng ngay tại webhook.
- `outbox` có unique index một phần `(channel, event_id) WHERE event_id IS NOT NULL`: nếu worker bị retry thì cũng không thể gửi 2 tin cho cùng một event.

### D-18. Migration chạy bằng service one-shot `migrate`
- `api` và `worker` chờ `migrate` kết thúc thành công (`service_completed_successfully`), tránh 2 tiến trình cùng chạy migration. `migrate` cũng đồng bộ `classes.yaml` vào DB. Cờ `enabled` chỉ được set ở lần tạo đầu tiên, để thao tác bật/tắt của admin không bị ghi đè khi khởi động lại.

### D-19. Cổng Postgres/Redis publish chỉ trên `127.0.0.1` (5433/6380)
- Test chạy từ host dùng DB riêng `gos_test`, được tạo lại mỗi phiên test. Conftest từ chối drop DB nếu tên không kết thúc bằng `_test`. Dùng cổng khác mặc định để không đụng Postgres/Redis có sẵn trên máy.

### D-20. Log JSON chỉ ghi `exc_type`, không ghi traceback
- Traceback có thể chứa giá trị secret trong message hoặc biến cục bộ. Log HTTP chỉ ghi path, không ghi query string, và tắt `uvicorn.access`.

---

## Phase 2 — Kênh & sự kiện

### D-21. Chống trùng bằng `INSERT … ON CONFLICT DO NOTHING RETURNING` và commit ngay
- Khi hai request trùng đến đồng thời, INSERT thứ hai bị chặn bởi row lock của INSERT thứ nhất. Sau khi INSERT thứ nhất commit, INSERT thứ hai đụng PK và không trả về dòng nào, tức là `duplicate`. Không cần lock Redis hay SELECT trước.
- **Phương án loại:** SELECT rồi mới INSERT (có race condition); lock trong Redis (thêm một điểm lỗi, và vẫn cần DB làm nguồn sự thật).
- Test: 2 và 8 bản sao gửi đồng thời bằng `asyncio.gather` đều cho đúng 1 job. Có thêm test e2e với arq thật.
- Lớp bảo vệ thứ 2: `_job_id` của arq bằng `msg:{channel}:{event_id}`. Lớp thứ 3: unique `(channel, event_id)` trên `outbox` (D-17). Nhờ vậy worker có bị retry thì cũng chỉ gửi đúng 1 tin.

### D-22. Thứ tự: chống trùng → bỏ qua → rate limit → enqueue (đúng mục 5)
- Mọi event hợp lệ đều được ghi vào `processed_events`, kể cả tin bị bỏ qua. Như vậy bảng sẽ lớn dần theo mọi tin nhắn trong nhóm, cần job dọn dữ liệu cũ (ví dụ giữ 7 ngày). Ghi vào "hướng cải thiện".
- Tin bị bỏ qua vẫn được ghi `request_logs` (outcome `ignored`) để thống kê. Lý do bỏ qua chỉ ghi vào log JSON, không thêm cột.

### D-23. Enqueue thất bại → xóa bản ghi `processed_events`, trả lỗi 5xx
- Nếu đã đánh dấu event là "đã thấy" mà không đưa được job vào hàng đợi, câu hỏi sẽ mất vĩnh viễn, vì lần gửi lại của nền tảng sẽ bị coi là trùng. Xóa đánh dấu thì lần retry được xử lý bình thường (có test).

### D-24. Rate limit kiểu fixed window 60 giây trong Redis, theo (lớp, user) và theo lớp
- Thông báo "gửi chậm lại" chỉ gửi **1 lần cho mỗi cửa sổ** (key `SET NX`). `security_events` loại `rate_limited` cũng chỉ ghi 1 lần mỗi cửa sổ, tránh spam bảng.
- **Phương án loại:** sliding window hoặc token bucket chính xác hơn ở biên cửa sổ, nhưng phức tạp hơn, không cần cho MVP.
- Thông báo được gửi qua job `send_notice` (bất đồng bộ), không gửi ngay trong request webhook, để khi dùng Zalo thật thì lệnh gọi API gửi tin không làm chậm webhook.

### D-25. Mở rộng `ChannelAdapter.send_reply` thêm `event_id` và `kind` (keyword-only, tùy chọn)
- Mục đích là idempotency khi gửi: adapter tự đảm bảo mỗi event chỉ gửi tối đa 1 tin. Chữ ký gốc ở CLAUDE.md vẫn tương thích.

### D-26. `POST /admin/classes/{id}/toggle` nhận body `{"enabled": bool}` thay vì đảo trạng thái
- Gọi lặp lại cho cùng kết quả (idempotent), không bị đảo ngược ngoài ý muốn khi client retry. Không cho bật/tắt `COMMON` (trả 404).

### D-27. Job trong hàng đợi chỉ chứa `user_hash`, không chứa user_id gốc hay tên hiển thị
- Hash được tính ngay ở webhook. **Lưu ý còn tồn đọng:** câu hỏi chưa được redact nằm tạm trong Redis cho tới khi worker xử lý. Ở Phase 4 sẽ redact trước khi enqueue (redact là thao tác thuần, nhanh), để Redis không bao giờ giữ secret.

### D-27b. (Đã duyệt) Che secret ngay tại webhook, trước khi enqueue
- Thực hiện ở Phase 4 cùng module redact. Worker vẫn redact lại lần nữa (phòng thủ nhiều lớp, thao tác idempotent).

### D-28. Trên Windows dùng `127.0.0.1` thay vì `localhost`
- `localhost` có thể phân giải sang `::1` trước, trong khi Docker chỉ publish trên IPv4, nên arq (timeout kết nối 1 giây) bị lỗi. Conftest tự đổi `localhost` thành `127.0.0.1`.

---

## Phase 3 — Kho tri thức (phần A: parse & chunk)

### D-29. Sinh `data/derived/` bằng Word (COM) hoặc LibreOffice; mặc định không ingest
- PDF được xuất bằng chính Word/LibreOffice (giữ bố cục và số trang thật, không đổi chữ). XLSX chứa nguyên văn 2 bảng FAQ, cộng cột "Mã mục" lấy từ heading ngay trên bảng.
- **Phương án loại:** tự vẽ PDF bằng PyMuPDF (phải nhúng font tiếng Việt, bố cục không giống tài liệu thật); `docx2pdf` (thêm thư viện, mà vẫn cần Word).
- Không ingest mặc định vì nội dung trùng với DOCX, sẽ gây kết quả truy xuất trùng lặp. Các file này dùng để demo và test parser PDF/XLSX, hoặc upload thủ công qua admin.

### D-30. Phần mở đầu tài liệu (mã tài liệu, dòng "LƯU Ý… giả lập") không được index
- Mã tài liệu (`DOC-GS-01`) được trích vào metadata `doc_code` để dùng khi trích dẫn. Dòng cảnh báo "giả lập" lặp lại ở mọi file, nếu index thì sẽ khớp nhiễu với nhiều câu hỏi.

### D-31. Ước lượng token = số ký tự / 3
- Chỉ dùng để quyết định kích thước chunk. Chi phí thật lấy token do provider trả về. Không thêm tokenizer (tiktoken) vì mỗi provider tách token khác nhau và chunk của học liệu mẫu đều nhỏ hơn nhiều so với ngưỡng.

### D-32. Mỗi chunk mở đầu bằng dòng ngữ cảnh `[Tài liệu: <mã> – <tên> · Mục: <mã mục> <tiêu đề>]`
- Giúp embedding và full-text khớp theo tên mục, và LLM biết chunk thuộc phần nào. Luật flag injection chỉ chạy trên phần thân chunk, không chạy trên dòng ngữ cảnh.

### D-33. PDF: bỏ dải 7% trên/dưới mỗi trang (header/footer lặp lại), chuẩn hóa ký tự bullet (Unicode Private Use → "•")
- Mỗi chunk PDF ứng với một cặp (mã mục, trang), location `trang N`. PDF không có mã mục thì mỗi trang là một chunk. Trang không có text thì ghi cảnh báo, không bỏ qua im lặng.

### D-34. Tên cột FAQ cấu hình được (`FAQ_QUESTION_COLUMNS`, `FAQ_ANSWER_COLUMNS`, `FAQ_SECTION_COLUMNS`), so khớp không phân biệt hoa thường và dấu
- Áp dụng cho cả bảng trong DOCX và sheet XLSX. Dòng thiếu câu hỏi hoặc câu trả lời thì ghi cảnh báo.

---

## Phase 3 — Kho tri thức (phần B: embedding, indexer, API)

### D-35. Model: OpenAI `gpt-6-luna` (dự phòng `gpt-5.6-luna`) + `text-embedding-3-small` với `dimensions=768`
- Người dùng chọn OpenAI. Theo trang công bố của OpenAI, API ID là `gpt-6-luna`, rẻ hơn khoảng 50% so với `gpt-5.6-luna`.
- `text-embedding-3-*` hỗ trợ tham số `dimensions` (rút gọn vector). Nhờ vậy giữ được `EMBEDDING_DIM=768` khớp cột DB, không cần migration. Vector ngắn hơn cũng nhẹ hơn cho index HNSW.
- **Phương án loại:** `text-embedding-3-large` (chất lượng cao hơn, đắt hơn nhiều; với kho vài chục chunk thì khác biệt không đáng). Gemini: đã viết provider nhưng không dùng mặc định.
- Đơn giá để `null` trong `config/pricing.yaml`. Người dùng tự điền từ trang giá chính thức.

### D-36. Danh tính một file nguồn = `(origin_scope, filename)`; file trộn chỉ được phép khi tải lên dưới `COMMON`
- `origin_scope` là lớp hoặc thư mục nơi file được tải lên. Nhờ cột này, hai lớp có thể có file trùng tên (ví dụ `FAQ.xlsx`) mà không ghi đè lẫn nhau.
- File tải lên cho một lớp mà chứa mục của lớp khác, hoặc của COMMON, sẽ bị **từ chối toàn bộ trước khi ghi DB** (`422`). Lý do: nếu không từ chối, giảng viên lớp A có thể vô tình (hoặc cố ý) đưa nội dung vào lớp B hay kho chung.
- Mục không có mã, hoặc có mã với tiền tố lạ, thì thuộc `origin_scope`.

### D-37. Hash nội dung tính theo từng phạm vi, không theo cả file
- Sửa phần GS của file 03 thì chỉ phần GS được embed lại, phần AUTO và COMMON giữ nguyên (tiết kiệm token). Nếu một phạm vi biến mất khỏi file trộn ở bản mới, document của phạm vi đó bị xóa (`removed`) để nội dung cũ không còn được truy xuất.

### D-38. Hash bao gồm `provider:model:dim` của embedding
- Đổi model embedding mà nội dung không đổi thì vẫn embed lại. Vector của các model khác nhau không so sánh được với nhau, nên giữ vector cũ sẽ làm truy xuất sai mà không có lỗi nào báo ra.

### D-39. Lưu file gốc (đặt tên theo sha256) trong `STORAGE_DIR` (volume `uploads`) để reindex
- Reindex = parse lại bản gốc + embed lại (`force`), tạo version mới. Cách này bao được cả khi parser hoặc chunker thay đổi, không chỉ khi model embedding thay đổi.
- Tên file người dùng gửi lên chỉ dùng để hiển thị (đã bỏ phần đường dẫn); file trên đĩa luôn mang tên `<sha256>.<ext>`, nên không thể path traversal.

### D-40. Upload và reindex chạy đồng bộ trong request admin
- Tài liệu khóa học nhỏ (vài giây để embed). Chạy qua worker sẽ cần thêm trạng thái theo dõi và polling. Trạng thái `processing` vẫn được ghi ra để admin thấy. Hướng mở rộng: chuyển sang job arq khi file lớn.
- Parse và đọc/ghi file chạy trong `asyncio.to_thread` để không chặn event loop.

### D-41. Embed lỗi → version mới `failed`, version cũ vẫn `active`
- Chunk mới, kích hoạt version mới, chuyển version cũ sang `superseded` và xóa chunk cũ đều nằm trong một transaction, chỉ chạy **sau khi** embed xong. Học viên không bao giờ thấy trạng thái nửa vời. Có test với embedder giả lập bị timeout.

### D-42. Embedding giả (`fake`): hashed bag-of-words + bigram, bỏ dấu, chuẩn hóa L2
- Tất định, chạy offline. Hai câu có chung từ thì cosine cao, nên test truy xuất ở Phase 4 vẫn có ý nghĩa mà không cần API. Token cho provider fake là ước lượng.

### D-43. Chunk bị flag injection: vẫn index + `security_events` (`prompt_injection`, source=document) + log cảnh báo
- Admin xem được tài liệu nào chứa câu mệnh lệnh để xử lý. Khi đưa vào prompt (Phase 4), các chunk này luôn được đóng gói là dữ liệu.
