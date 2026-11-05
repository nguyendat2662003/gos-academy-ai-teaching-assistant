# Prompt dùng với Claude Code — GOS Academy AI Teaching Assistant

`CLAUDE.md` là đặc tả dự án (Claude Code tự đọc mỗi phiên). File này chứa các prompt bạn dán vào chat, mỗi phase một prompt.

## Chuẩn bị (làm tay trước khi mở Claude Code)

1. Tạo thư mục dự án và chạy `git init`.
2. Copy `CLAUDE.md` vào thư mục gốc.
3. Copy file đề bài vào `docs/de_bai.pdf`.
4. Đặt học liệu HR gửi vào `data/samples/<ma_lop>/`, ví dụ `data/samples/ai_automation/` và `data/samples/google_sheets/`. Nếu chưa rõ file nào thuộc lớp nào, cứ để chung trong `data/samples/`, Phase 0 sẽ phân loại giúp.
5. Tạo `.gitignore` có dòng `.env` ngay từ đầu.
6. Không dán API key vào chat với Claude Code. Khi tới Phase 3, tự copy `.env.example` thành `.env` và tự điền key.

---

## Prompt Phase 0 — Khảo sát (dán đầu tiên)

```
Đọc kỹ CLAUDE.md và docs/de_bai.pdf. Ở phase này CHƯA viết code.

Hãy làm lần lượt:

1. Liệt kê toàn bộ file trong data/samples/. Với mỗi file cho biết: định dạng, thuộc lớp nào (theo thư mục hoặc nội dung), cấu trúc (có số trang / heading / sheet / cột hỏi-đáp không), và rủi ro khi parse (trang ảnh scan, bảng phức tạp, công thức, ô gộp...). Mở thử nội dung để xác minh, đừng đoán theo tên file.

2. Đối chiếu với 7 tình huống bắt buộc ở mục 13 CLAUDE.md:
   - Học liệu có nội dung "RAG khác Fine-tuning" không, nằm ở lớp nào, file nào, trang/mục nào?
   - Lớp AI Automation có nội dung về lỗi n8n 401 / xác thực credential không?
   - Có tài liệu chính sách học phí / ưu đãi không?
   - Có câu hỏi nào xuất hiện được ở cả hai lớp để test tình huống 5 không?
   Báo cáo rõ cái gì đủ, cái gì thiếu. KHÔNG tự viết thêm nội dung vào học liệu.

3. Đề xuất nội dung config/classes.yaml (class_id, tên lớp, group_id giả lập, giảng viên phụ trách để placeholder).

4. Rà soát CLAUDE.md: chỉ ra chỗ nào mâu thuẫn, rủi ro, thiếu, hoặc bạn đề xuất thay đổi (kèm lý do). Đừng tự sửa CLAUDE.md.

5. Lập kế hoạch chi tiết cho Phase 1 (danh sách file sẽ tạo, thứ tự làm).

Trình bày ngắn gọn, rồi DỪNG chờ tôi duyệt.
```

---

## Prompt Phase 1 — Nền tảng

```
Thực hiện Phase 1 theo mục 16 CLAUDE.md và kế hoạch đã duyệt.

Lưu ý:
- Dùng image Postgres có sẵn pgvector; migration đầu tiên tạo extension vector.
- Cột embedding dùng EMBEDDING_DIM đọc từ config.
- Tạo .env.example với giá trị giả rõ ràng (vd change-me), kiểm tra .gitignore đã chặn .env.
- docker-compose có healthcheck cho postgres và redis; api và worker chờ dịch vụ sẵn sàng.
- README: phần "Chạy nhanh" (copy .env, docker compose up, chạy migration, chạy test).

Kết thúc theo quy ước mục 15 rồi dừng.
```

## Prompt Phase 2 — Kênh & sự kiện

```
Thực hiện Phase 2 theo mục 16 CLAUDE.md (đặc tả webhook ở mục 5 và 6).

Yêu cầu test bắt buộc:
- chữ ký sai và timestamp quá 300 giây → 401 + security_event
- tin nhắn có is_bot=true → ignored
- tin không có trigger /hoi → ignored
- group không ánh xạ lớp, lớp đang tắt bot → ignored
- vượt rate limit → rate_limited, thông báo không bị gửi lặp lại
- gửi cùng event_id 2 lần ĐỒNG THỜI (asyncio.gather) → đúng 1 job và 1 bản ghi outbox

Viết scripts/send_mock_event.py nhận --group, --user, --text, --duplicate, tự ký HMAC bằng WEBHOOK_SECRET đọc từ môi trường.
Worker ở phase này chỉ cần trả lời giả (echo) vào outbox; logic RAG làm ở Phase 4.

Kết thúc theo quy ước mục 15 rồi dừng.
```

## Prompt Phase 3 — Kho tri thức

```
Thực hiện Phase 3 theo mục 16 CLAUDE.md (đặc tả ở mục 7).

Trước khi viết indexer và gọi embedding thật:
1. Viết parsers + chunker trước.
2. Chạy thử trên 1 file mỗi định dạng trong data/samples và cho tôi xem 3–5 chunk đầu của mỗi file kèm location và số token ước tính.
3. Dừng để tôi kiểm tra chất lượng parse/chunk.

Sau khi tôi duyệt mới làm tiếp: provider embedding (gemini, openai, fake), indexer, API document CRUD + versioning + reindex, scripts/ingest_samples.py (in thống kê số chunk theo lớp, số trang bị cảnh báo không có text, số chunk bị flag injection, token embedding đã dùng).

Test bắt buộc: cập nhật tài liệu có nội dung khác → chunk cũ không còn được truy xuất; upload lại file trùng hash → bỏ qua; xóa tài liệu → không còn chunk.

Kết thúc theo quy ước mục 15 rồi dừng.
```

## Prompt Phase 4 — Truy xuất & agent

```
Thực hiện Phase 4 theo mục 16 CLAUDE.md (luồng ở mục 5, RAG mục 7, sinh câu trả lời mục 8, bảo mật mục 9).

Trình tự:
1. Hybrid retrieval có filter class_id bắt buộc. Viết test khẳng định mọi kết quả đều thuộc đúng lớp, và không có hàm search nào thiếu tham số class_id.
2. Redact secret, guard injection, phân loại chủ đề chính sách.
3. Viết system prompt vào app/agent/prompts.py và cho tôi xem toàn văn. DỪNG chờ tôi duyệt prompt.
4. Sau khi duyệt: query rewrite, gọi LLM trả JSON, verify citation, ghép nguồn từ metadata, ngữ cảnh hội thoại có TTL, retry/timeout.

Test với provider fake cho tình huống 1, 2, 4, 5, 7. Tình huống 7 phải gồm cả injection trong câu hỏi và injection nằm trong một tài liệu fixture ở tests/fixtures/ (không sửa data/samples).

Cuối phase: chạy thật (LLM thật) 1 câu hỏi cho mỗi lớp qua scripts/send_mock_event.py và cho tôi xem phản hồi trong outbox.

Kết thúc theo quy ước mục 15 rồi dừng.
```

## Prompt Phase 5 — Handoff, FAQ, admin, demo

```
Thực hiện Phase 5 theo mục 16 CLAUDE.md (mục 10 và mục 12).

- Admin API cho handoff ticket: lọc theo lớp/trạng thái, trả lời, gửi câu trả lời vào nhóm qua adapter, promote vào FAQ (index ngay cho đúng lớp), export CSV.
- Trang admin tối giản (Jinja2) bảo vệ bằng ADMIN_API_KEY.
- Trang /demo: hai khung chat cho hai nhóm (AI Automation, Google Sheets), ô nhập và nút gửi; server ký HMAC thay trình duyệt; phản hồi hiển thị bằng polling outbox; có nút "gửi trùng event" để demo chống trùng. Chỉ bật khi APP_ENV=dev.

Test: tình huống 3 và luồng end-to-end "câu hỏi bị handoff → giảng viên trả lời → promote FAQ → hỏi lại câu tương tự → bot trả lời có nguồn FAQ".

Kết thúc theo quy ước mục 15 rồi dừng.
```

## Prompt Phase 6 — Giám sát & chi phí

```
Thực hiện Phase 6 theo mục 16 CLAUDE.md (mục 11).

- Bảo đảm mọi outcome đều ghi request_logs với đủ trường.
- /admin/stats theo lớp và theo ngày, có latency trung bình và p95, token, chi phí ước tính.
- /admin/security-events.
- config/pricing.yaml để placeholder, ghi chú nguồn cần tra.

Chạy một kịch bản gồm khoảng 20 tin nhắn hỗn hợp (trả lời, handoff, trùng, injection, rate limit) rồi đối chiếu stats với log để chứng minh số liệu khớp.

Kết thúc theo quy ước mục 15 rồi dừng.
```

## Prompt Phase 7 — Đánh giá & tài liệu

```
Thực hiện Phase 7 theo mục 16 CLAUDE.md.

1. Đề xuất 30–40 câu cho data/eval/golden.yaml dựa trên học liệu thực tế: khoảng 1/3 câu cố tình không có trong tài liệu, vài câu hỏi nối tiếp, vài câu hỏi chéo lớp, vài câu injection. Cho tôi duyệt trước khi chạy.
2. Viết scripts/run_scenarios.py và scripts/eval_rag.py, chạy với LLM thật, đề xuất giá trị RETRIEVAL_MIN_SCORE dựa trên kết quả (kèm bảng số liệu).
3. Viết docs/ARCHITECTURE.md (sơ đồ Mermaid: luồng dữ liệu, ranh giới phân quyền lớp, adapter), docs/TEST_REPORT.md (test case, kết quả thực tế, lỗi tồn đọng, hướng cải thiện — ghi trung thực, không tô hồng), docs/COST_AND_ZALO.md (công thức chi phí theo số câu hỏi/ngày dùng số token đo được, điều kiện cần để tích hợp Zalo OA/GMF, các điểm cần xác minh trên tài liệu chính thức).
4. Hoàn thiện README.

Kết thúc theo quy ước mục 15 rồi dừng.
```

---

## Prompt dùng khi cần

**Audit bảo mật trước khi nộp**

```
Đóng vai người chấm khó tính của GOS Academy. Kiểm tra repo theo 4 ràng buộc cứng ở mục 1 CLAUDE.md:
- quét toàn bộ repo và lịch sử git tìm chuỗi giống secret;
- liệt kê mọi đường code truy vấn bảng chunks/faq_entries và xác nhận đều lọc class_id;
- kiểm tra log và DB sau khi chạy run_scenarios có chứa secret, tên hiển thị hay user_id gốc không;
- thử thêm 10 biến thể prompt injection (tiếng Việt có dấu, không dấu, tiếng Anh, chèn trong câu hỏi dài) và báo kết quả.
Liệt kê vấn đề theo mức độ nghiêm trọng, chưa sửa, chờ tôi duyệt.
```

**Khi test fail lặp lại**

```
Dừng sửa. Giải thích nguyên nhân gốc của lỗi này, liệt kê 2–3 hướng xử lý kèm đánh đổi, rồi chờ tôi chọn.
```

**Chuẩn bị phỏng vấn sau demo**

```
Giải thích cho tôi toàn bộ luồng từ lúc webhook nhận tin đến lúc phản hồi được gửi, chỉ rõ file và hàm ở từng bước.
Sau đó hỏi tôi lần lượt 10 câu phỏng vấn khó (bao gồm 5 câu ở mục IX đề bài), mỗi lần một câu, chấm và góp ý câu trả lời của tôi.
```

---

## Mẹo

- Mỗi phase nên bắt đầu một phiên mới để ngữ cảnh gọn; CLAUDE.md được đọc lại tự động.
- Commit sau mỗi phase đã duyệt, để dễ quay lại nếu phase sau làm hỏng.
- Đọc diff trước khi chấp nhận, nhất là phần retrieval, guard và prompt — đây là những chỗ bạn sẽ bị hỏi kỹ nhất.
