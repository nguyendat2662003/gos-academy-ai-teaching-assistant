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

HANDOFF_NO_CONTEXT = (
    "Câu hỏi này mình chưa tìm thấy căn cứ trong tài liệu của lớp nên chưa thể trả lời chính xác. "
    "Mình đã chuyển tới giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}."
)

HANDOFF_POLICY = (
    "Câu hỏi về học phí, ưu đãi, hoàn phí, chứng chỉ hoặc quyền lợi cần bộ phận phụ trách xác nhận, "
    "tài liệu của lớp chưa có thông tin chính thức nên mình không tự trả lời. Mình đã chuyển tới giảng viên/bộ phận "
    "tư vấn, dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}."
)

HANDOFF_LOW_CONFIDENCE = (
    "Mình chưa chắc chắn về câu trả lời dựa trên tài liệu của lớp nên không muốn trả lời sai. "
    "Mình đã chuyển tới giảng viên, thầy/cô dự kiến phản hồi trong vòng 01 ngày làm việc. Mã yêu cầu: {ticket}."
)

PARTIAL_NOTE = (
    "Phần {parts} chưa có trong tài liệu của lớp nên mình chưa thể xác minh. "
    "Mình đã chuyển phần này tới giảng viên (mã yêu cầu: {ticket})."
)

ERROR_FRIENDLY = (
    "Xin lỗi, hệ thống trợ giảng đang gặp sự cố tạm thời nên chưa trả lời được. "
    "Mình đã chuyển câu hỏi tới giảng viên. Mã yêu cầu: {ticket}."
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


def ticket_code(ticket_id: int) -> str:
    return f"#H-{ticket_id:04d}"
