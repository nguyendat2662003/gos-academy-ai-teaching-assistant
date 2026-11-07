# Chi phí vận hành & điều kiện tích hợp Zalo thật

> Tài liệu không chứa đơn giá nào. Đơn giá token phải lấy từ trang giá chính thức của provider, điền vào
> [config/pricing.yaml](../config/pricing.yaml) (kèm ngày kiểm tra). Mọi số token dưới đây là **số đo thật**
> trên hệ thống (OpenAI `gpt-6-luna` + `text-embedding-3-small`, ngày 2026-11-05), không phải ước đoán.

## 1. Chi phí theo từng câu hỏi (đo thật)

| Loại xử lý | Gọi LLM? | Token LLM vào / ra | Token embedding |
|---|---|---|---|
| Trả lời / trả lời một phần | có | TB **1.808 / 176** (p95 vào 2.456; max 2.833) | ~22 (câu truy vấn) |
| Chuyển giảng viên vì `low_confidence` (LLM báo không có căn cứ) | có | ~1.500 / ~100 | ~22 |
| Chuyển giảng viên vì `policy` (học phí, chứng chỉ…) | **không** | 0 | ~20 (truy xuất để tìm căn cứ chính sách) |
| Chuyển giảng viên vì `no_context` (dưới ngưỡng) | **không** | 0 | ~20 |
| Từ chối (injection, xin secret, hỏi lớp khác) | **không** | 0 | 0 |
| Bị bỏ qua / trùng / vượt rate limit | không | 0 | 0 |
| Câu hỏi nối tiếp (có lịch sử) | thêm 1 lượt viết lại câu hỏi | + vài trăm token | — |

Chi phí một lần, khi index tài liệu:
- Toàn bộ học liệu mẫu (3 file, 32 chunk): **6.514 token embedding**.
- Mỗi FAQ được duyệt: khoảng 100–130 token.
- Nội dung không đổi (trùng hash) thì không embed lại.

Phần lớn token đầu vào là các đoạn tài liệu (top-5 chunk) và system prompt, không phải câu hỏi.

## 2. Công thức ước tính theo tháng

Gọi:
- `Q` = số câu hỏi gửi bot (`@Trợ lý` / `/hoi`) mỗi tháng;
- `a` = tỷ lệ câu cần gọi LLM (trả lời, một phần hoặc `low_confidence`);
- `P_in`, `P_out`, `P_emb` = đơn giá USD cho 1 triệu token, lấy từ `pricing.yaml`.

```
Chi phí LLM       ≈ Q × a × (1.808 × P_in + 176 × P_out) / 1.000.000
Chi phí embedding ≈ (Q × 22 + token ingest mỗi tháng) × P_emb / 1.000.000
```

Ví dụ minh họa **khối lượng** (không phải chi phí): 2 lớp × 30 học viên × 2 câu/ngày ≈ `Q = 3.600` câu/tháng. Lấy `a = 1` để có cận trên:

- Token LLM vào ≈ 3.600 × 1.808 ≈ **6,5 triệu**
- Token LLM ra ≈ 3.600 × 176 ≈ **0,63 triệu**
- Token embedding ≈ 3.600 × 22 + 6.514 ≈ **0,09 triệu**

→ Chi phí tháng ≈ `6,5 × P_in + 0,63 × P_out + 0,09 × P_emb` (USD). Thay đơn giá thật vào là ra con số.

Hệ thống tự tính con số này từ token thật: `/admin/stats` hoặc mục "Thống kê & chi phí" trên `/admin/ui` (D-70). Model chưa điền giá thì chi phí hiển thị `null` kèm tên model thiếu giá, không bao giờ tính thành 0.

## 3. Hạ tầng

Bốn tiến trình chạy bằng `docker compose`: API, worker, PostgreSQL + pgvector, Redis. Với vài lớp học, một máy ảo nhỏ là đủ (CPU-bound rất ít; thời gian chủ yếu là chờ LLM). Chi phí hạ tầng phụ thuộc nhà cung cấp; tài liệu này không đưa giá. Các hạng mục cần tính:
- máy chủ hoặc dịch vụ container;
- PostgreSQL có backup;
- tên miền + HTTPS cho webhook Zalo;
- lưu trữ file học liệu;
- giám sát log.

## 4. Đòn bẩy giảm chi phí đã có trong thiết kế

1. **Quyết định trước khi gọi LLM:** guard, chính sách và ngưỡng điểm truy xuất trả về 0 token LLM cho câu từ chối, câu học phí và câu rõ ràng lạc đề.
2. **Ngưỡng `RETRIEVAL_MIN_SCORE = 0.35`** được hiệu chỉnh bằng `eval_rag.py`. Ngưỡng này chặn trước khoảng 1/3 số câu không có căn cứ mà không làm mất câu có căn cứ nào (D-74).
3. **FAQ đã duyệt:** câu hỏi lặp lại được trả lời từ một chunk ngắn, chính xác.
4. **Không embed lại nội dung không đổi** (hash theo phạm vi + model).
5. **Rate limit** theo học viên và theo lớp chặn spam tốn tiền.
6. **Nếu cần giảm thêm** (chưa làm):
   - giảm `RETRIEVAL_TOP_K` xuống 3–4, vì top-5 chiếm phần lớn token đầu vào;
   - dùng model rẻ hơn cho bước viết lại câu hỏi;
   - cache câu trả lời theo câu hỏi chuẩn hóa trong từng lớp, nhớ xóa cache khi tài liệu đổi version.

## 5. Tích hợp Zalo thật

### Đã chắc chắn (ràng buộc của dự án)

- **Không** tự động hóa tài khoản Zalo cá nhân và **không** dùng thư viện không chính thức hoặc reverse-engineer (ràng buộc cứng số 4). Có test kiểm tra danh sách dependency.
- Kênh hợp lệ duy nhất: **Zalo Official Account (OA) + Group Message Framework (GMF)**, khi được Zalo cấp quyền.
- Code đã sẵn chỗ: [app/channels/zalo.py](../app/channels/zalo.py) có `ZaloGMFAdapter` cùng interface với adapter mô phỏng (`verify`, `parse`, `send_reply`). `POST /webhooks/zalo` hiện trả `501`. Pipeline, ticket, log và thống kê không cần sửa, vì mọi kênh đều được chuẩn hóa về `IncomingMessage`.

### Cần xác minh trên tài liệu chính thức (developers.zalo.me) trước khi làm

Trang tài liệu chính thức tải nội dung bằng JavaScript, nên công cụ của tôi không đọc được. Các mục dưới đây là **danh sách việc phải kiểm tra**, không phải thông tin đã xác minh:

| Hạng mục | Cần xác minh | Ghi chú |
|---|---|---|
| Điều kiện OA | OA cần xác thực loại nào; GMF có cần gói dịch vụ hay đăng ký riêng không | |
| Quyền | Phạm vi (scope) của access token để quản lý nhóm và gửi tin nhóm | Một SDK bên thứ ba ghi là `manage_group` và `group_message` ([nguồn, chưa xác minh](https://app.unpkg.com/@warriorteam/redai-zalo-sdk@1.32.17/files/docs/GROUP_MANAGEMENT.md)) |
| Gửi tin nhóm | Endpoint, định dạng, loại tin (text, mention…), giới hạn tần suất / quota | SDK trên dùng `https://openapi.zalo.me/v3.0/oa/group/message` ([nguồn, chưa xác minh](https://app.unpkg.com/@warriorteam/redai-zalo-sdk@1.32.17/files/dist/services/group-message.service.js)) |
| Nhận sự kiện | Tên sự kiện tin nhắn nhóm, payload (group id, người gửi, nội dung, id sự kiện để chống trùng) | Ánh xạ về `IncomingMessage` |
| Xác thực webhook | Cơ chế chữ ký của Zalo (thuật toán, header, khóa nào) | Thay cho HMAC tự định nghĩa của webhook mô phỏng |
| Token | Thời hạn access token và cách làm mới bằng refresh token | Lưu token như secret (biến môi trường / secret store), không ghi log |
| Nhóm | Điều kiện để OA vào được nhóm học viên; giới hạn số thành viên / số nhóm | Một lớp có thể có nhiều nhóm (`channel_groups`) |
| Tin của chính OA | Cách nhận biết tin do OA gửi, để bỏ qua (`is_from_bot`) | Chống vòng lặp bot tự trả lời |

### Các bước khi đã có quyền

1. Đăng ký webhook HTTPS trỏ tới `/webhooks/zalo`. Cài `verify()` theo cơ chế chữ ký chính thức; sai chữ ký thì trả 401 và ghi `security_events`, giống webhook mô phỏng.
2. Cài `parse()`: sự kiện tin nhắn nhóm chuyển thành `IncomingMessage`, với `event_id` lấy từ id sự kiện hoặc id tin của Zalo để chống trùng.
3. Cài `send_reply()`: gọi API gửi tin nhóm, có timeout và retry, và chỉ trả `True` khi Zalo xác nhận đã nhận. Theo AUTO-07: gửi thất bại thì không được coi là đã trả lời.
4. Khai báo `group_id` thật của từng lớp trong `config/classes.yaml` (`channel: zalo`). `class_id` vẫn chỉ đến từ bảng này.
5. Bật dần từng lớp bằng `/admin/classes/{id}/toggle`; theo dõi `/admin/stats` và `/admin/security-events`.
