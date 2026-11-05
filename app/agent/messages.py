"""Every sentence the bot sends to students lives here (Vietnamese), so wording is easy to adjust."""

RATE_LIMITED_USER = (
    "Bạn đang gửi câu hỏi hơi nhanh 😊 Mình sẽ tạm dừng nhận câu hỏi mới của bạn trong khoảng 1 phút, "
    "sau đó bạn gửi lại giúp mình nhé."
)

RATE_LIMITED_CLASS = (
    "Nhóm đang có nhiều câu hỏi cùng lúc nên mình cần tạm dừng khoảng 1 phút. "
    "Các bạn vui lòng gửi lại sau ít phút nhé."
)

# Phase 2 placeholder until the RAG agent (Phase 4) is wired in.
ECHO_RECEIVED = "Mình đã nhận câu hỏi: “{question}”. (Chế độ thử nghiệm: chưa bật trả lời bằng tài liệu.)"
