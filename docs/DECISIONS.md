# Nhật ký quyết định kỹ thuật (ADR rút gọn)

Mỗi mục: **Bối cảnh → Quyết định → Phương án loại → Lý do**. Mã `D-xx` được tham chiếu trong code/comment.

---

## Phase 0 — Khảo sát học liệu & đề bài

### D-01. Kho dùng chung `COMMON` bên cạnh kho từng lớp
- **Bối cảnh:** Học liệu (`00_Huong_dan...`, M-02) yêu cầu "FAQ chung được truy xuất cho cả hai lớp". Thiết kế ban đầu lại quy định mỗi tài liệu gắn đúng một lớp.
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

### D-12. Thư viện bổ sung ngoài tech stack ban đầu
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
- Mục đích là idempotency khi gửi: adapter tự đảm bảo mỗi event chỉ gửi tối đa 1 tin. Chữ ký interface ban đầu vẫn tương thích.

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

---

## Phase 4 — Truy xuất & agent (phần A: retrieval, redact, guard, policy, prompt)

### D-44. Che secret bằng regex theo thứ tự cụ thể → chung, chạy ngay tại webhook (D-27b)
- Thứ tự áp dụng: private key, `sk-…`, `AIza…`, `gh*_…`, JWT, `Bearer …`, cặp `password=` / `mật khẩu:` / `token là` (chỉ che phần giá trị nên câu vẫn đọc được), chuỗi hex ≥ 32 ký tự, chuỗi base64 ≥ 32 ký tự có cả chữ và số.
- Hàm che có tính idempotent, nên worker chạy lại lần nữa cũng không làm hỏng dữ liệu. Phát hiện secret thì ghi `security_events` loại `secret_in_message` (chỉ lưu tên loại, không lưu giá trị), và job mang cờ `secret_detected` để câu trả lời nhắc học viên thu hồi key.
- Test dùng key giả được ghép lúc chạy, nên trong repo không có chuỗi nào giống key thật.

### D-45. Guard chỉ là lớp phòng thủ đầu tiên
- Ba nhóm luật regex chạy trên câu đã bỏ dấu: injection (dùng lại luật tài liệu ở D-10, cộng các mẫu riêng cho câu hỏi như "system prompt", "your instructions"), đòi bí mật, đòi dữ liệu lớp khác.
- Kể cả khi guard bỏ sót, SQL vẫn chỉ trả chunk của lớp đó và prompt vẫn coi mọi đầu vào là dữ liệu. Guard chỉ giúp từ chối sớm và ghi được sự kiện bảo mật.
- `GUARD_LLM_ENABLED` (phân loại thêm bằng LLM) chưa bật trong MVP.

### D-46. "Đòi bí mật" = động từ yêu cầu + danh từ bí mật + **chủ sở hữu** (nội bộ / của GOSTECH / của hệ thống / của bạn)
- Nếu chặn mọi câu có chữ "API key" thì câu hỏi hợp lệ "Em có cần kiểm tra lại API key không?" cũng bị chặn. Có test cho cả hai chiều. Trong 8 tin mẫu của HR, guard chỉ chặn đúng E008.
- "Lớp khác": các cụm `lớp khác / class khác`, mã lớp khác, hoặc `lớp|class|nhóm + <alias của lớp khác>` (alias khai trong `classes.yaml`). Tên công cụ đứng một mình không bị chặn, vì lớp n8n có thể hỏi hợp lệ về việc ghi dữ liệu vào Google Sheets.

### D-47. Chủ đề nhạy cảm nhận diện bằng từ khóa; "căn cứ chính sách" phải có số liệu cụ thể
- Các nhóm: học phí, ưu đãi, hoàn tiền, chứng chỉ, điểm số (không dùng chữ "điểm" đứng một mình, vì câu "RAG khác Fine-tuning ở **điểm** nào?" sẽ bị nhận nhầm), khiếu nại, thông tin cá nhân.
- Một chunk chỉ được coi là căn cứ chính sách khi vừa nói đúng chủ đề, vừa có con số (tiền, %, hạn "trước N…"), và không phải câu khẳng định "không có thông tin". Vì vậy COMMON-03 không được coi là căn cứ, và câu hỏi học phí sẽ handoff `policy`.

### D-48. Truy xuất: một hàm duy nhất `hybrid_search(session, *, class_id, …)`
- `class_id` là tham số keyword bắt buộc, không có giá trị mặc định. Truyền `COMMON` hoặc mã lớp lạ sẽ bị `ValueError`.
- Bộ lọc `class_id IN (lớp, COMMON)` và điều kiện "tài liệu `active` hoặc FAQ `active`" nằm trong cùng một `_base_query`, dùng chung cho nhánh vector, nhánh full-text và bước đếm IDF.
- Có test cấu trúc: mọi coroutine public trong `app.retrieval.search` đều phải có `class_id` dạng keyword bắt buộc; chỉ 3 module được phép tham chiếu `Chunk` (search, indexer, admin_documents).
- pgvector 0.8: dùng `SET LOCAL hnsw.iterative_scan = relaxed_order` để HNSW quét tiếp khi bộ lọc `WHERE` loại bớt hàng, nhờ đó vẫn trả đủ k kết quả.
- Điểm dùng cho ngưỡng = cosine của kết quả vector tốt nhất. RRF với k = 60.

### D-49. Full-text: OR các từ trong câu hỏi, chấm điểm bằng tổng IDF của các từ khớp
- Postgres tách tiếng Việt theo âm tiết, nên các âm tiết phổ biến ("xử", "lý", "lỗi") lấn át từ hiếm mang tính quyết định ("401", "unauthorized"). Đã thử dùng `ts_rank_cd` rồi lọc theo tỷ lệ 30% số chunk, nhưng vẫn xếp AUTO-07 lên đầu.
- Cách chốt: `idf(t) = ln(1 + N/df(t))` tính trên các chunk thuộc phạm vi của lớp (một câu SQL đếm), điểm của chunk = Σ idf của các từ nó chứa. Với câu hỏi 401, AUTO-03 lên đầu nhánh full-text.
- Từ chỉ gồm ký tự `\w` nên không thể chèn cú pháp `to_tsquery`. Có thêm một danh sách stopword nhỏ.
- **Hạn chế:** câu hỏi gõ không dấu sẽ không khớp full-text (cột `tsv` giữ dấu). Nhánh vector bù được phần này. Hướng cải thiện: dùng extension `unaccent`.

### D-50. Prompt: mọi dữ liệu không tin cậy đều được bọc thẻ và escape HTML
- Tài liệu nằm trong `<tai_lieu id nguon muc [canh_bao]>`, lịch sử trong `<lich_su>`, câu hỏi trong `<cau_hoi>`. Ký tự `<`, `>`, `&` trong nội dung được escape, nên không thể tự đóng thẻ để giả làm chỉ dẫn (có test).
- Chunk bị flag mang thuộc tính `canh_bao="chua_cau_lenh"`. LLM chỉ trả id chunk (`c_N`); tên nguồn do code ghép từ metadata.
- Đầu ra được validate bằng Pydantic (`LLMAnswer`); có thêm trường `unanswered_parts` cho outcome `partial` (D-04).

---

## Phase 4 — Truy xuất & agent (phần B: sinh câu trả lời, kiểm tra, ngữ cảnh, retry)

### D-51. LLM gọi ở chế độ JSON; retry tự viết, tắt retry của SDK
- OpenAI: Chat Completions với `response_format={"type": "json_object"}` và `max_completion_tokens`. Gemini: `response_mime_type="application/json"` (chưa được test vì không có key).
- `providers/retry.py`: `asyncio.wait_for` (timeout) + retry chỉ cho `TransientLLMError` (429 / 5xx / timeout / lỗi kết nối), độ trễ `base·2^n` cộng jitter, tối đa `LLM_MAX_RETRIES`. Lỗi `PermanentLLMError` (400, 401, model sai...) không retry.
- **Phương án loại:** dùng retry có sẵn của SDK OpenAI (tiện, nhưng mỗi provider một kiểu, khó test và khó giải thích). Có test: 2 lần lỗi tạm thời rồi thành công → 3 lần gọi; lỗi vĩnh viễn → 1 lần gọi; timeout → `1 + LLM_MAX_RETRIES` lần gọi rồi tạo ticket `error`.

### D-52. LLM giả (`fake`) là bản giả tất định có luật rõ ràng, không phải mô hình ngôn ngữ
- Nó đọc đúng prompt mà code dựng ra. Câu dạng "A khác B" được tách thành 2 ý. Một ý được coi là có căn cứ khi thân chunk chứa đủ từ khóa (với câu hỏi nguyên khối: ≥ 50% số từ và tối thiểu 2 từ). Ý thiếu căn cứ được ghi vào `unanswered_parts`.
- Có thể gắn `script` để giả lập LLM trả lời sai hoặc có ý xấu (JSON hỏng, trích dẫn bịa, câu trả lời chứa key). Nhờ đó test được bước kiểm tra đầu ra.
- Chất lượng trả lời thật được đo bằng LLM thật (`run_scenarios.py`, `eval_rag.py`, Phase 7). Test offline chỉ chứng minh **logic điều phối** đúng.

### D-53. Thứ tự trong worker: che secret → guard → lịch sử → viết lại câu hỏi → truy xuất → chính sách → ngưỡng → LLM → kiểm tra → ghép câu trả lời
- Guard chạy trước mọi lệnh gọi tốn tiền (embedding, LLM). Câu hỏi chính sách không có căn cứ và câu hỏi dưới ngưỡng đều **không gọi LLM** (có test `llm.calls == []`).
- Chỉ viết lại câu hỏi khi có lịch sử. Nếu bước viết lại lỗi thì dùng câu gốc, không làm hỏng cả yêu cầu.
- Kiểm tra chính sách cần kết quả truy xuất, nên chạy sau bước truy xuất (thiết kế ban đầu đặt bước phân loại chính sách trước bước truy xuất, nhưng kết quả cuối cùng như nhau).

### D-54. Worker idempotent ở 3 điểm
1. Đầu job: nếu `outbox` đã có event thì dừng (retry sau khi đã gửi sẽ không gọi lại LLM, tránh tốn tiền).
2. Ticket: tìm theo `request_id` trước khi tạo, nên retry không tạo ticket thứ hai.
3. Log và lịch sử chỉ ghi **sau khi** gửi thành công. Unique index trên outbox (D-17) là chốt chặn cuối cùng.

### D-55. Outcome `partial` = câu trả lời phần có căn cứ + câu "Phần “X” chưa có trong tài liệu…" + ticket `partial_coverage` (lưu `unanswered_parts` trong `check_detail`)

### D-56. Căn cứ chính sách phải nằm trong **cùng một câu** (sửa lỗi do test bắt được)
- Phiên bản đầu xét cả chunk, nên COMMON-01 ("…kết luận chính thức về **học phí**…" và "…trong vòng **01** ngày…") bị coi là căn cứ, và bot sẽ trả lời câu hỏi giảm học phí. Test tình huống 3 đã bắt được lỗi này.
- Nay căn cứ chỉ tính số tiền hoặc phần trăm (không tính mốc thời gian), và phải cùng câu với từ khóa chủ đề.

### D-57. `POST /api/ask` dùng chung pipeline, chạy đồng bộ, tin `class_id` do bên gọi (server-to-server, `X-API-Key`)
- Vẫn che secret, chạy guard, kiểm tra lớp tồn tại và đang bật (`404` / `409`). Không áp rate limit vì bên gọi là backend tin cậy. Kênh ghi log là `api`.

### D-58. Lịch sử hội thoại lưu câu hỏi đã viết lại (độc lập) + thân câu trả lời (không kèm dòng nguồn); không lưu các lượt bị từ chối
- Lọc theo `(class_id, user_hash)`, nên cùng một học viên ở lớp khác không có lịch sử (có test). TTL và giới hạn số lượt được áp ngay trong SQL.

### D-59. Test dùng `RETRIEVAL_MIN_SCORE = 0`; ngưỡng có test riêng
- Cosine của embedding giả không có ý nghĩa tuyệt đối, nên các test tình huống để LLM giả quyết định. Một test riêng đặt ngưỡng 0.99 để khẳng định nhánh `no_context` không gọi LLM. Giá trị thật sẽ hiệu chỉnh bằng `eval_rag.py` với embedding OpenAI (Phase 7).

## Phase 4 — Chạy thật (OpenAI `gpt-6-luna` + `text-embedding-3-small`, dim 768)

### D-60. Ngưỡng `RETRIEVAL_MIN_SCORE = 0.5` quá cao; đề xuất tạm `0.3` (hiệu chỉnh chính thức bằng eval ở Phase 7)
Cosine top-1 đo được trên 14 câu thật (8 tin mẫu HR + các tình huống ở §13):

| Câu hỏi | top | Kỳ vọng | Với 0.5 | Với 0.3 |
|---|---|---|---|---|
| E001–E005, S5 (2 lớp) | 0.611–0.788 | trả lời | đúng | đúng |
| E006 "Lớp mình học thứ mấy?" (có trong AUTO-CLASS-01) | 0.449 | trả lời | **sai: chuyển `no_context`** | đúng |
| S1 "RAG khác Fine-tuning…" (AUTO-05) | 0.394 | `partial` | **sai: chuyển `no_context`** | đúng (`partial`, unanswered = Fine-tuning) |
| S4 Kubernetes / Docker Swarm | 0.343 | chuyển giảng viên | đúng (`no_context`) | đúng (LLM báo `not_answerable` → `low_confidence`) |

- Câu hỏi tiếng Việt ngắn có cosine thấp ngay cả khi tài liệu có đáp án. Khoảng cách giữa "có căn cứ" (0.394) và "không có" (0.343) rất hẹp, nên ngưỡng không thể là lớp chặn chính.
- Thiết kế: ngưỡng chỉ là bộ lọc rẻ, để tiết kiệm lời gọi LLM cho câu hỏi rõ ràng lạc đề. Lớp chặn chính chống bịa là bước kiểm tra JSON + trích dẫn (bước 14), và S4 cho thấy bước này đã chặn đúng. Đặt ngưỡng thấp an toàn hơn đặt cao: sai do ngưỡng thấp tốn thêm khoảng 1.5k token; sai do ngưỡng cao làm mất câu trả lời đúng.
- Câu chính sách (S3, E007) và câu bị guard chặn (S7, E008) được quyết định trước bước truy xuất hoặc trước ngưỡng, nên không phụ thuộc giá trị này.

## Phase 5 — Handoff, FAQ, admin, demo

### D-61. FAQ đã duyệt luôn thuộc lớp của ticket, không do bên gọi chọn
- `POST /admin/handoffs/{id}/promote` không nhận `class_id`. Lớp lấy từ ticket, mà ticket được tạo từ `group_id` phía server. Vì vậy giảng viên không thể vô tình đưa câu trả lời lớp này vào FAQ lớp khác (ràng buộc cứng số 2).
- Một FAQ = một bản ghi `faq_entries` + một chunk `source_type=faq` (`faq_entry_id`, location `FAQ giảng viên #N`). Truy xuất chỉ lấy chunk của FAQ `active` (đã có từ Phase 4).
- Thứ tự: embed **trước**, rồi ghi entry + chunk + `promoted_to_faq` trong **một transaction**. Nếu provider lỗi thì không có gì được ghi dở. Câu hỏi và câu trả lời đi qua `redact()`, và chunk vẫn qua luật flag injection như tài liệu.
- Mỗi ticket chỉ duyệt một lần (`409 already_promoted`), nên không tạo FAQ trùng.
- Test kiến trúc "chỉ các module được phép đọc/ghi `Chunk`" đã bắt module mới. Tôi đã xem lại rồi mới thêm vào danh sách (chỉ INSERT, lớp lấy từ ticket).

### D-62. Câu trả lời của giảng viên gửi vào nhóm qua chính adapter, `kind=instructor`, `event_id=NULL`
- Unique của outbox chỉ áp với `event_id` khác null (D-17), nên giảng viên có thể gửi lại có chủ đích, còn bot vẫn không gửi 2 lần cho một event.
- Ticket đến từ `/api/ask` không có nhóm, nên `post_to_group` → `409`. Kênh không gửi được (Zalo stub) → `501`.
- Câu trả lời giảng viên cũng được che secret trước khi lưu, vì giảng viên cũng có thể vô tình dán token.

### D-63. Trang admin/demo là "vỏ tĩnh" + JSON API dùng header `X-Admin-Key`; không dùng cookie/session
- Chỉ có một cơ chế xác thực (header, so sánh hằng thời gian), không cần CSRF token vì không có cookie. Trang HTML không chứa dữ liệu hay secret, nên có thể phục vụ không cần khóa. Khóa người dùng gõ vào được giữ trong `sessionStorage` (mất khi đóng tab).
- Loại bỏ: HTTP Basic auth (trình duyệt cache thông tin đăng nhập, khó "đăng xuất"); session cookie (phải thêm CSRF và bảng session).

### D-64. Chống XSS: CSP với nonce theo request + chèn dữ liệu bằng `textContent`
- Câu hỏi học viên và câu trả lời LLM là dữ liệu không tin cậy, hiển thị trên trang của giảng viên. Mọi dữ liệu được chèn bằng text node (helper `h()`), không bao giờ dùng `innerHTML`.
- `Content-Security-Policy: default-src 'none'; script-src 'nonce-…'; style-src 'nonce-…'; connect-src 'self'; frame-ancestors 'none'`. Kể cả khi có lỗ chèn HTML, script lạ cũng không chạy. Có test kiểm tra header và nonce.

### D-65. CSV export: UTF-8 BOM + vô hiệu hóa công thức
- BOM để Excel/Google Sheets đọc đúng tiếng Việt.
- Ô bắt đầu bằng `= + - @` (hoặc tab/CR) được thêm dấu `'` phía trước. Lý do: câu hỏi do học viên gõ, nếu là `=HYPERLINK(...)` hay `=IMPORTXML(...)` sẽ chạy như công thức khi giảng viên mở file (CSV/formula injection). Không xuất `user_hash`.

### D-66. `/demo`: server tự ký HMAC và gọi `/webhooks/mock` của chính nó trong tiến trình (httpx `ASGITransport`)
- Tin demo đi qua **đúng** đường của sự kiện thật: kiểm tra chữ ký, chống trùng, trigger, rate limit, hàng đợi. Nhờ vậy video chứng minh luồng thật, không phải đường tắt. Trình duyệt không bao giờ thấy `WEBHOOK_SECRET`.
- Chỉ bật khi `APP_ENV=dev` (khác thì `404` cho cả trang lẫn API) và API yêu cầu `X-Admin-Key`. Nhóm phải thuộc `classes.yaml`.
- Trang chỉ hiện tin bot đọc từ outbox. Tin học viên chỉ hiện ở trình duyệt đã gửi, vì server không lưu nguyên văn câu hỏi (chỉ lưu bản đã che, trong lịch sử/ticket).
- Loại bỏ: gọi thẳng `handle_incoming` (bỏ qua bước kiểm tra chữ ký, demo kém thuyết phục); WebSocket/SSE (polling 1,5 giây là đủ cho demo và đơn giản hơn).

### D-67. Embedding token khi duyệt FAQ: hiện chỉ trả trong response + log, chưa cộng vào thống kê
- Bảng `faq_entries` chưa có cột token. Phase 6 sẽ quyết định ghi vào đâu (cột mới hoặc `request_logs`) khi làm `/admin/stats`. Mỗi FAQ khoảng 100 token, nhỏ hơn nhiều so với một lần ingest.

### D-68. Câu hỏi đếm/liệt kê: cấm khẳng định về "toàn bộ tài liệu"; không chiều theo học viên khi không có căn cứ (lỗi phát hiện khi chạy thật)
- Lỗi: "có mấy công thức dùng sheet" (lớp GS). Truy xuất top-5 không lấy được GS-03 (EOMONTH, TODAY) vì đoạn đó không chứa chữ "công thức"; thử top-12 cũng không lấy được. LLM chỉ thấy 5 đoạn nhưng trả lời "tài liệu có 3 hàm". Học viên nhắc "còn thiếu EOMONTH", bot xin lỗi rồi chốt "4 hàm", vẫn sai (thực tế có 5 hàm: SUMIFS, COUNTIFS, EOMONTH, TODAY, IMPORTRANGE).
- Bản chất: RAG đưa cho LLM vài đoạn liên quan nhất, không phải toàn bộ giáo trình. Vì vậy mọi khẳng định kiểu "tài liệu có N…/chỉ có…" đều không có căn cứ (ràng buộc cứng số 3).
- Sửa (prompt, quy tắc 10–11): coi các khối là trích đoạn; với câu hỏi đếm/liệt kê thì chỉ nêu những gì thấy, nói rõ "trong các phần mình tìm được", không chốt tổng số, đưa phần cần danh sách đầy đủ vào `unanswered_parts` (thành `partial` + ticket); học viên bảo thiếu/sai thì chỉ xác nhận điều có trong khối.
- Kiểm chứng bằng LLM thật: lượt 1 ra `partial` (không chốt tổng, có ticket); "còn thiếu EOMONTH" thì xác nhận kèm nguồn GS-03; "còn thiếu VLOOKUP" (không có trong giáo trình) thì không đồng ý, ra `partial`.
- Còn tồn tại: câu trả lời cho câu hỏi liệt kê vẫn có thể chưa đầy đủ, nhưng đã nói thật và có ticket. Giảng viên trả lời ticket và duyệt vào FAQ là đủ để các lần sau trả lời đúng. Phương án chưa làm: với câu hỏi đếm/liệt kê, đưa toàn bộ học liệu của lớp vào ngữ cảnh khi kho nhỏ (học liệu mẫu khoảng 4k token). Phương án này chính xác hơn nhưng không mở rộng được khi giáo trình thật lớn, và thêm một nhánh xử lý cần giải thích.

## Phase 6 — Giám sát & chi phí

### D-69. Ghi đủ "sự thật" để tính tiền: token + tên model trên từng nguồn chi phí (migration 0003)
- `request_logs.embedding_model`, `documents.embedding_model`, `faq_entries.embedding_tokens/embedding_model` (đóng D-67). Mỗi khoản chi đều biết đã dùng bao nhiêu token của model nào: LLM (gồm cả lượt viết lại câu hỏi), embedding câu truy vấn, embedding lúc ingest (mọi version, kể cả version đã `superseded`, vì đã trả tiền), embedding lúc duyệt FAQ.
- Dòng cũ (trước 0003) không có tên model embedding thì tạm tính theo `EMBEDDING_MODEL` hiện tại. Đây là xấp xỉ, đã ghi rõ trong code.
- Thêm index `request_logs(created_at)` cho thống kê theo khoảng ngày trên mọi lớp.

### D-70. Chi phí = token × đơn giá **hiện tại** trong `pricing.yaml`, tính lúc truy vấn; `request_logs.cost_usd` là ảnh chụp lúc ghi
- Token là dữ liệu thật lấy từ response của provider; chi phí là con số suy ra. Đơn giá do người dùng điền tay, có thể điền **sau** khi đã chạy, nên `/admin/stats` tính lại từ token. Điền giá xong thì lịch sử cũ cũng có chi phí.
- `cost_usd` của từng request được ghi lúc ghi log, để xem chi phí một request cụ thể. Khi đơn giá không đổi thì hai con số khớp nhau (có test).
- Giá chưa có (null): chi phí là `null`, không phải 0. `pricing.cost_complete = false` và `models_missing_price` nêu tên model. Không có token thì chi phí là 0, nên tin bị bỏ qua hay bị từ chối trước khi gọi LLM vẫn được tính đủ.
- Tên model kèm ngày do provider trả về (`gpt-x-2026-01-01`) được tra theo tiền tố dài nhất khớp (`gpt-x`).
- `pricing.yaml` trong repo chỉ có placeholder; có test bảo đảm không ai lỡ commit giá tự bịa.
- Loại bỏ: chỉ cộng `cost_usd` đã ghi (giá điền sau thì lịch sử mãi là null); hardcode giá (giá phải điền tay từ trang giá chính thức).

### D-71. Latency = từ lúc webhook nhận tin đến lúc gửi trả lời (thời gian học viên chờ), báo trung bình + p95
- Tính gồm cả thời gian chờ trong hàng đợi, chỉ cho các outcome do bot xử lý (`answered|partial|handoff|refused|error`). Latency của tin bị bỏ qua hay bị trùng chỉ là thời gian của webhook, nếu tính vào sẽ kéo số liệu xuống sai.
- p95 dùng `percentile_cont(0.95)` của Postgres. Đo thật (OpenAI): một câu đơn lẻ mất 2–6 giây; 8 tin đến cùng lúc mỗi tin mất khoảng 7,5–8,8 giây; có một ngoại lệ 323 giây (job chờ lúc worker bị dừng). Trung bình bị kéo lệch bởi ngoại lệ, nên cần xem thêm p95.

### D-72. "Ngày" = ngày theo giờ Việt Nam
- SQL nhóm theo `timezone('Asia/Ho_Chi_Minh', created_at)`. Python lọc `from/to` bằng offset cố định +07:00 vì Việt Nam không có giờ mùa hè, và trên Windows Python không có sẵn cơ sở dữ liệu múi giờ (khỏi thêm thư viện `tzdata`). Có test cho mốc 23:59 / 00:01.
- Các hằng số trong biểu thức GROUP BY được render inline, không dùng tham số bind. Nếu bind, Postgres thấy `$1` ở SELECT và `$2` ở GROUP BY là hai biểu thức khác nhau và báo lỗi.

### D-73. Phạm vi số liệu
- Tin trùng được thống kê ở dòng `(chưa xác định)`, vì chống trùng chạy trước khi ánh xạ nhóm sang lớp; lọc theo lớp sẽ không thấy các dòng này.
- `tickets_by_reason` tính mọi request có lý do chuyển giảng viên: `handoff`, `partial` (`partial_coverage`) và `error`. Đối chiếu khớp với bảng `handoff_tickets`.
- `/admin/security-events` chỉ trả 12 ký tự đầu của user hash: đủ để nhận ra cùng một người, không lộ thêm gì. Chi tiết sự kiện đã được che khi ghi.
- Kiểm chứng trên stack thật: mọi số đếm, token, ticket theo lý do và sự kiện bảo mật trong `/admin/stats` khớp với SQL tính trực tiếp trên các bảng.

## Phase 7 — Đánh giá & tài liệu

### D-74. `RETRIEVAL_MIN_SCORE = 0.35`, hiệu chỉnh bằng `eval_rag.py` trên 40 câu golden (embedding OpenAI)
- Câu có căn cứ: cosine top-1 thấp nhất **0.391** (GS-12 "Công thức trả về 0 thì kiểm tra gì?"), trung vị 0.586. Câu không có căn cứ hoặc thuộc lớp khác: từ 0.333 đến **0.642** (GS-17 "Hàm QUERY…" có điểm cao vì giống chủ đề Google Sheets). Hai nhóm **chồng lên nhau**, nên ngưỡng không thể là lớp chặn chính (khẳng định lại D-60).
- Ngưỡng 0.35: 30/30 câu có căn cứ đi qua; 2/6 câu không căn cứ bị chặn ngay, không tốn LLM. Biên an toàn so với câu có căn cứ thấp nhất là 0.041. Script tự đề xuất 0.36 (biên 0.03); 0.35 chặn đúng 2 câu đó mà biên rộng hơn, nên chọn 0.35.
- Lớp chặn chính vẫn là bước kiểm tra JSON + trích dẫn: ở chế độ `--full`, cả 6/6 câu không căn cứ đều thành handoff, không câu nào bị bịa.
- Chạy `--full` ở 0.35: vẫn quyết định đúng 40/40; GS-20 (0.333) và AU-16 (0.348) chuyển sang `no_context`, không gọi LLM; tổng token LLM giảm từ 73.523 (ngưỡng 0.3) xuống 69.094.
- Khi thêm học liệu hoặc đổi model embedding, chạy lại `eval_rag.py` và hiệu chỉnh lại.

### D-75. `eval_rag.py --full` chạy pipeline thật trong **một transaction rồi rollback**
- `AsyncSession(join_transaction_mode="create_savepoint")` trên một connection đã `begin()`. Các lệnh `commit()` trong pipeline chỉ giải phóng savepoint; cuối script rollback toàn bộ. Vì vậy ticket và security event sinh ra khi đánh giá không làm bẩn thống kê. Có test kiểm tra sau eval bảng ticket vẫn rỗng.
- Gọi `answer_question` trực tiếp (không qua webhook hay outbox): đo đúng quyết định của bot, không gửi tin vào nhóm nào. Mỗi câu dùng một `user_hash` mới, nên không có lịch sử.
- Loại bỏ: chạy qua webhook rồi xóa dữ liệu sau (dễ sót, xóa nhầm dữ liệu thật); DB riêng cho eval (phải ingest lại bằng embedding thật).

### D-76. Thiết kế bộ golden (`data/eval/golden.yaml`, 40 câu)
- Mỗi câu ghi `class_id`, `expect` (`answer|partial|handoff|refused`), `sections` chứa đáp án và `kind` (`material|not_in_material|other_class|policy|injection`).
- Có câu hỏi giống hệt nhau ở 2 lớp, và câu hỏi của lớp này đặt vào nhóm lớp kia (`other_class`), để đo cách ly lớp.
- Không dùng câu Kubernetes: FAQ #1 tạo khi chạy thử Phase 5 vẫn còn trong DB dev.
- Test bảo đảm mọi mã mục kỳ vọng có thật trong học liệu (tránh gõ nhầm), và mỗi `kind` đều có câu.
- Chỉ số: hit@1, hit@k, MRR, chunk lớp khác bị truy xuất hoặc trích dẫn (phải = 0), quyết định đúng (chính xác và theo nhị phân trả lời/không), số câu bịa, trích dẫn đúng mục, token, thời gian.
- Kết quả thật: [EVAL_RESULTS.md](EVAL_RESULTS.md). Quyết định đúng 40/40, hit@5 100%, rò rỉ 0.

### D-77. `run_scenarios.py` kiểm tra bằng DB, không chỉ đọc câu trả lời
- 7 tình huống đi qua webhook thật (có ký HMAC) trên stack. Mỗi tình huống có các kiểm tra cụ thể: outcome, lý do ticket, nguồn chỉ thuộc lớp mình + COMMON, key giả không còn ở bảng nào, đúng 1 bản ghi outbox cho event gửi trùng đồng thời, có `security_event`, không gọi LLM cho câu chính sách/injection, phản hồi không chứa giá trị secret nào của server (so sánh trong process, không in ra).
- Script trả exit code 1 nếu có kiểm tra không đạt, nên dùng được trong CI. Kết quả thật: [SCENARIOS_RESULTS.md](SCENARIOS_RESULTS.md), 7/7 đạt.

### D-78. Tự audit bảo mật thành test (`tests/test_security_audit.py`)
- Ràng buộc 1:
  - quét mọi file có thể commit để tìm chuỗi có dạng khóa thật;
  - `.env` bị ignore; `.env.example` chỉ có placeholder;
  - log của cả một luồng (gồm chữ ký sai, gọi admin) không chứa key, khóa admin, secret webhook, tên hiển thị, user id thô hay nội dung tin nhắn.
- Ràng buộc 2: `class_id` của hàm truy xuất là keyword-only và không có mặc định; payload webhook không có trường lớp.
- Ràng buộc 4: không có thư viện Zalo không chính thức hay công cụ điều khiển trình duyệt trong dependency; adapter Zalo chỉ là khung.
- Bảng ánh xạ ràng buộc → bằng chứng nằm trong [TEST_REPORT.md](TEST_REPORT.md).

### D-79. `alembic/env.py`: `fileConfig(..., disable_existing_loggers=False)`
- Mặc định của `logging.config.fileConfig` là vô hiệu hóa mọi logger đã tạo. Khi migration chạy trong cùng process với ứng dụng (fixture test `migrated_db`), logger `app` bị tắt hoàn toàn. Trên Docker không bị vì `migrate` là container riêng.
- Lỗi được test audit log (D-78) phát hiện: test chỉ hỏng khi chạy sau một test có migration. Sửa ở gốc thay vì bật lại logger trong test.

### D-80. Mount `config/` vào container (chỉ đọc) thay vì chỉ chép vào image
- Lỗi do người dùng gặp: đã điền giá vào `config/pricing.yaml` nhưng thống kê vẫn báo thiếu đơn giá. Nguyên nhân là `COPY . .` đưa `config/` vào image lúc build, nên sửa file trên máy rồi `--force-recreate` vẫn đọc bản cũ (hướng dẫn trước đó sai).
- Sửa: `./config:/app/config:ro` cho api, worker, migrate. Sửa `pricing.yaml` hoặc `classes.yaml` rồi `docker compose up -d --force-recreate api worker` là có hiệu lực, không cần build lại. Vẫn cần restart vì cả hai file được đọc một lần rồi cache (`lru_cache`). Mount chỉ đọc để container không thể sửa cấu hình.

### D-81. Tin chuyển giảng viên: 3 cách diễn đạt mỗi lý do, chọn theo mã ticket
- Trong một nhóm đông, một câu cố định lặp lại liên tục nghe máy móc. Mỗi lý do (`no_context`, `low_confidence`, `policy`, `error`) có 3 biến thể trong `messages.py`.
- Biến thể được chọn bằng `ticket_id % 3`, không dùng `random`: các ticket liên tiếp nhận câu khác nhau, còn job bị retry gửi lại đúng câu cũ (giữ idempotent, test được).
- Câu vẫn là mẫu cố định, không do LLM viết, và không lặp lại câu hỏi của học viên. Test bảo đảm mọi biến thể có mã yêu cầu và chỉ hứa "01 ngày làm việc" (COMMON-01/04), không có mốc thời gian nào khác.
- Test giá: bỏ test "file giá chỉ được chứa null", vì giá do người dùng tự điền từ trang chính thức là hợp lệ. (Ràng buộc "có giá thì bắt buộc `checked_at`" từng thêm ở đây đã bỏ, xem D-85.)

### D-82. `docker compose up` tự ingest `data/samples` trong service `migrate`
- Vấn đề: người khác (HR, người chấm) clone repo về sẽ có DB trống. Nếu quên chạy `ingest_samples.py` thì mọi câu hỏi đều bị chuyển giảng viên (`no_context`), trông như bot hỏng.
- Chọn: thêm `python scripts/ingest_samples.py` vào cuối lệnh của `migrate`, sau `alembic upgrade head` và `seed`. Chạy mỗi lần `up` vẫn an toàn: nội dung không đổi bị bỏ qua nhờ `content_hash` (D-38), nên chỉ lần đầu, khi file thay đổi hoặc khi đổi model embedding thì mới tốn token. `migrate` chạy xong thì api/worker mới khởi động, nên không có ingest chạy song song.
- Script trả mã thoát 1 nếu có file bị từ chối hoặc phạm vi index lỗi (vd key embedding sai). Trước đây lỗi chỉ được in ra rồi thoát 0, nên `migrate` sẽ báo thành công với kho rỗng. Giờ `migrate` lỗi thì api/worker không chạy, và `docker compose logs migrate` ghi rõ `INGEST FAILED` (chỉ in loại lỗi, không in nội dung lỗi có thể chứa thông tin nhạy cảm). Phiên bản cũ đang `active` vẫn được giữ.
- Đánh đổi đã chấp nhận: key sai thì cả stack không lên, thay vì chạy với bot trả lời sai/không trả lời. Ingest qua admin API không đổi.
- Loại: commit vector/dump DB vào repo (phụ thuộc model, dễ lệch với học liệu, dump chứa log/ticket vận hành); service `ingest` riêng (thêm một service mà lợi ích không đáng kể).

### D-83. Phân quyền khu quản trị: khóa quản trị + khóa giảng viên theo lớp
- Vấn đề: trước đây mọi giảng viên dùng chung `ADMIN_API_KEY`, nên giảng viên lớp này đọc, trả lời và duyệt FAQ được cho ticket lớp khác, sửa tài liệu lớp khác; `approved_by` là ô tự khai. Bot vẫn cách ly dữ liệu đúng, nhưng con người thì không.
- Chọn: `INSTRUCTOR_API_KEYS=CLASS=key,...` trong `.env`. Server so khớp khóa trong header `X-Admin-Key` (hằng thời gian, duyệt hết danh sách) và sinh `Principal(role, name, class_id)`. Mọi truy vấn ticket/tài liệu/thống kê của giảng viên bị ghim vào `class_id` của khóa: đối tượng lớp khác trả 404 (không lộ sự tồn tại), xin lọc lớp khác trả 403. Thao tác toàn hệ thống (bật/tắt bot, sự kiện bảo mật, `/demo`, tài liệu tải lên dưới COMMON vì nó nuôi nhiều lớp) chỉ cho quản trị.
- `approved_by` khi giảng viên duyệt FAQ = tên giảng viên trong `classes.yaml`, bỏ qua giá trị client gửi.
- Kiểm tra lúc khởi động: mã lớp phải có trong `classes.yaml` (COMMON không có giảng viên), mỗi khóa ≥ 16 ký tự, không trùng nhau, không trùng khóa quản trị. Bật `hide_input_in_errors` cho Settings để khóa sai định dạng không bị in vào log lỗi.
- Giữ tên header `X-Admin-Key` (= "khóa vào khu quản trị") để client và test cũ không đổi; thiết kế ban đầu chỉ có một khóa quản trị, đây là phần mở rộng.
- Loại: tài khoản + mật khẩu + session (giai đoạn C của đề bài, cần lưu mật khẩu, CSRF, quên mật khẩu…); JWT có claim lớp (thêm thư viện và vòng đời token mà MVP chưa cần). Khi lên SSO chỉ cần thay `require_staff`, phần `Principal` giữ nguyên.

### D-84. Trang `/demo` dạng ứng dụng chat + khung sự kiện webhook
- Vấn đề: bản cũ là hai khung chat đơn giản; người xem video không thấy rằng mỗi tin là một sự kiện webhook có ký HMAC, và tình huống 6 (trùng) chỉ thử được bằng script.
- Chọn: bố cục quen thuộc của ứng dụng chat nhóm trên máy tính (thanh điều hướng, danh sách hội thoại, bong bóng tin, trích dẫn tin được trả lời, trạng thái "Đã nhận") để HR dễ hình dung sản phẩm thật. Không dùng logo, tên hay tài nguyên của Zalo; trang ghi rõ "MÔ PHỎNG".
- Khung "Sự kiện webhook": hiện payload, `X-Timestamp`, phản hồi của webhook và tin bot gửi ra. Chữ ký không bao giờ gửi về trình duyệt. `POST /demo/api/replay` gửi lại đúng sự kiện (1 lần hoặc 2 lần đồng thời) để quay tình huống 6 ngay trên giao diện; "tài khoản bot khác" (`is_bot=true`) để quay chống vòng lặp.
- Tin học viên gõ trên trang chỉ lưu trong `sessionStorage` của tab; tin của bot luôn đọc lại từ outbox. Không thêm bảng hay API lưu tin học viên chỉ để phục vụ demo.

### D-85. `checked_at` trong `pricing.yaml` là tùy chọn
- Đơn giá OpenAI của các model đã chọn do người dùng điền tay từ trang giá chính thức. Ngày kiểm tra không ảnh hưởng đến cách tính chi phí, nên không bắt buộc.
- Bỏ test bắt buộc `checked_at`. Trường vẫn còn: nếu điền thì trang admin hiển thị cạnh dòng chi phí; để trống thì không hiển thị gì.
- Không đổi: giá không bao giờ hardcode trong code; model chưa có giá thì `cost_usd = null`, không tính 0.
