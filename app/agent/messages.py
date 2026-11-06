"""Every sentence the bot sends to students lives here (Vietnamese), so wording is easy to adjust.

Ticket codes look like "#H-0012". The 1-working-day promise comes from COMMON-01 (do not promise more: COMMON-04).
"""

RATE_LIMITED_USER = (
    "Bạn đang gửi câu hỏi hơi nhanh 😊 Mình sẽ tạm dừng nhận câu hỏi mới của bạn trong khoảng 1 phút, "
    "sau đó bạn gửi lại giúp mình nhé."
)

RATE_LIMITED_CLASS = (
    "Nhóm đang có nhiều câu hỏi cùng lúc nên mình cần tạm dừng khoảng 1 phút. "
    "Các bạn vui lòng gửi lại sau ít phút nhé."
)

SOURCES_PREFIX = "📚 Nguồn: "

SECRET_WARNING = (
    "⚠️ Tin nhắn của bạn có chứa thông tin giống khóa bí mật (API key/token/mật khẩu). Mình đã ẩn nó đi. "
    "Bạn nên thu hồi/đổi khóa đó ngay và đừng dán thông tin bí mật lên nhóm nhé."
)

# Handoff wordings: several variants per reason so a busy group does not see the same sentence over and over.
# The variant is picked by ticket id (pick()), so a retried job re-sends exactly the same text. Every variant
# keeps the same facts: no grounds -> forwarded to the instructor -> "01 ngày làm việc" (COMMON-01, never another
# promise: COMMON-04) -> ticket code. Placeholders: {ticket}.
HANDOFF_NO_CONTEXT = (
    "Câu hỏi này mình chưa tìm thấy căn cứ trong tài liệu của lớp nên chưa thể trả lời chính xác. "
    "Mình đã chuyển tới giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
    "Mình chưa tìm thấy nội dung này trong học liệu của lớp nên chưa thể trả lời chắc chắn. Câu hỏi đã được "
    "chuyển tới giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
    "Tài liệu của lớp hiện chưa có thông tin để trả lời câu này, nên mình không muốn đoán. Mình đã gửi câu hỏi "
    "cho giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
)

HANDOFF_POLICY = (
    "Câu hỏi về học phí, ưu đãi, hoàn phí, chứng chỉ hoặc quyền lợi cần bộ phận phụ trách xác nhận, "
    "tài liệu của lớp chưa có thông tin chính thức nên mình không tự trả lời. Mình đã chuyển tới giảng viên/bộ phận "
    "tư vấn, dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
    "Các câu hỏi về học phí, ưu đãi, hoàn phí, chứng chỉ hay quyền lợi cần được bộ phận phụ trách xác nhận chính "
    "thức, nên mình không tự trả lời. Mình đã chuyển tới giảng viên/bộ phận tư vấn, dự kiến phản hồi trong vòng "
    "01 ngày làm việc. Mã yêu cầu: {ticket}.",
    "Tài liệu của lớp chưa có thông tin chính thức về học phí, ưu đãi, hoàn phí, chứng chỉ hoặc quyền lợi, nên mình "
    "xin phép không trả lời để tránh sai lệch. Yêu cầu đã được chuyển tới giảng viên/bộ phận tư vấn, dự kiến phản "
    "hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
)

HANDOFF_LOW_CONFIDENCE = (
    "Mình chưa chắc chắn về câu trả lời dựa trên tài liệu của lớp nên không muốn trả lời sai. "
    "Mình đã chuyển tới giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
    "Mình tìm được vài nội dung liên quan nhưng chưa đủ căn cứ để trả lời chính xác câu này. Mình đã chuyển tới "
    "giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
    "Để tránh trả lời sai, mình đã chuyển câu hỏi này tới giảng viên vì tài liệu của lớp chưa đủ rõ để mình xác "
    "nhận. Thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}.",
)

PARTIAL_NOTE = (
    "Phần {parts} chưa có trong tài liệu của lớp nên mình chưa thể xác minh. "
    "Mình đã chuyển phần này tới giảng viên (mã yêu cầu: {ticket})."
)

ERROR_FRIENDLY = (
    "Xin lỗi, hệ thống trợ giảng đang gặp sự cố tạm thời nên chưa trả lời được. "
    "Mình đã chuyển câu hỏi tới giảng viên. Mã yêu cầu: {ticket}.",
    "Xin lỗi bạn, trợ giảng đang gặp sự cố tạm thời nên chưa xử lý được câu hỏi này. "
    "Mình đã chuyển câu hỏi tới giảng viên. Mã yêu cầu: {ticket}.",
    "Hệ thống trợ giảng vừa gặp sự cố tạm thời nên mình chưa trả lời ngay được. "
    "Câu hỏi của bạn đã được chuyển tới giảng viên. Mã yêu cầu: {ticket}.",
)

REFUSED_INJECTION = (
    "Mình chỉ có thể hỗ trợ các câu hỏi về nội dung học của lớp theo đúng quy tắc của trợ giảng, "
    "nên không thể làm theo yêu cầu này. Bạn cứ hỏi về bài học nhé!"
)

REFUSED_SECRET = (
    "Mình không thể cung cấp khóa API, token, mật khẩu hay cấu hình nội bộ. Nếu cần quyền truy cập cho bài thực "
    "hành, bạn liên hệ giảng viên qua kênh riêng nhé — đừng đăng thông tin bí mật lên nhóm."
)

REFUSED_CROSS_CLASS = (
    "Mình chỉ hỗ trợ bằng tài liệu của lớp này, không thể cung cấp tài liệu hay thông tin của lớp khác. "
    "Nếu bạn học thêm lớp đó, hãy hỏi trong nhóm của lớp tương ứng nhé."
)


INSTRUCTOR_REPLY = "👩‍🏫 Giảng viên trả lời yêu cầu {ticket}\n❓ {question}\n\n{answer}"


def pick(variants: tuple[str, ...], ticket_id: int) -> str:
    """Deterministic variant by ticket id: consecutive tickets differ, a retried job re-sends the same text."""
    return variants[ticket_id % len(variants)]


def ticket_code(ticket_id: int) -> str:
    return f"#H-{ticket_id:04d}"
