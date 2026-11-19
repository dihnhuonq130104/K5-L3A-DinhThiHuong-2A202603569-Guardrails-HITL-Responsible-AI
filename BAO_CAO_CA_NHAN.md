# Báo cáo cá nhân — Guardrails, HITL và Responsible AI

**Họ và tên:** Đinh Thị Hương  
**MSSV:** 2A202603569  
**Lớp:** K5-L3A  
**Ngày thực hiện:** 19/11/2026

> Bản thảo tổng hợp từ code và kết quả chạy trong repo, có AI hỗ trợ soạn thảo. Học viên cần đọc lại, chỉnh phần nhận xét theo hiểu biết của mình trước khi sử dụng. Tài liệu này được bổ sung theo yêu cầu riêng, không thay thế báo cáo tự động `outputs/lab_report.md` và các artifact chấm bài.

## 1. Mục tiêu và phạm vi

Bài lab sử dụng chatbot VinBank giả lập để kiểm tra cách bảo vệ một AI agent trước prompt injection, lộ thông tin, gửi dữ liệu ra địa chỉ không được phép và gọi model quá nhiều lần. Mọi credential dùng làm mục tiêu tấn công đều là dữ liệu giả của bài lab.

Có ba agent: Blue là agent được bổ sung lớp phòng thủ; Red là mục tiêu cố ý có phòng thủ yếu; Red Advance là mục tiêu có regex và NVIDIA NeMo Guardrails. Phần triển khai tập trung vào các checkpoint bắt buộc: guardrails, pipeline, kiểm thử và red-team. Module HITL và LLM-as-Judge tùy chọn chưa được triển khai thêm thành ứng dụng xét duyệt hoàn chỉnh.

## 2. Môi trường và cấu hình thực tế

- Python 3.12 và NeMo Guardrails 0.24.1. Python 3.14 trên máy không tương thích với phiên bản NeMo mà repo yêu cầu.
- Blue gọi Liquid trực tiếp tại `https://api.liquid.ai/openai/v1`, model `lfm3-1.7b`.
- Red và Red Advance gọi qua `https://9router.openailab.tech/v1`, model `gpt-5.6-luna`. NeMo self-check dùng cùng endpoint, model và key của Red.
- API key được đọc từ `.env` local; file này được Git bỏ qua.

Cấu hình trên được sử dụng theo yêu cầu của người làm bài. Nó khác cấu hình gốc trong tài liệu: Blue dùng OpenRouter; Red mặc định dùng `gpt-4o-mini` hoặc `gemini-3.5-flash`. Kết quả dưới đây chỉ phản ánh model đã gọi thực tế, không được coi là bằng chứng đã chạy các model mặc định đó.

## 3. Các phần đã triển khai

### Guardrails đầu vào và đầu ra

Đầu vào được chuẩn hóa Unicode, loại ký tự vô hình rồi kiểm tra các dấu hiệu đổi vai, bỏ qua chỉ dẫn, yêu cầu system prompt và khai thác thông tin nội bộ. Bộ lọc chủ đề chỉ cho phép câu hỏi phù hợp với nghiệp vụ ngân hàng. Một trường hợp được kiểm tra là chỉ dẫn độc hại nằm trong email bên ngoài; nội dung email hợp lệ vẫn phải được xử lý như dữ liệu.

Đầu ra được kiểm tra và che bằng `[REDACTED]` khi chứa email, CMND/CCCD, số điện thoại, API key, password hoặc secret giả. Số điện thoại có dấu cách, dấu gạch nối và dấu ngoặc cũng được xử lý. Bộ dữ liệu PII có sẵn được kiểm tra đủ 10 trường hợp.

### Pipeline, rate limit và quan sát

Thứ tự xử lý là rate limit → input guardrails → model → output guardrails. Rate limiter sử dụng cửa sổ trượt theo từng user ID. Runtime truyền đúng danh tính vào plugin để một người dùng hết hạn mức không làm người dùng khác bị chặn.

Audit log ghi request ID, người dùng, nội dung đã che, quyết định chặn, lớp xử lý và độ trễ. Monitoring tổng hợp số request, số bị chặn và số lần chạm rate limit. Audit và monitoring được gắn quanh các request trong bộ chạy kiểm thử.

### Egress và HITL

Chính sách egress kiểm tra HTTPS, hostname chính xác, cổng cho phép và payload. Domain giả mạo hoặc payload chứa PII/secret bị từ chối bằng code, không dựa vào lời đồng ý của model.

Repo có sẵn `security_boundary.py` minh họa yêu cầu approval đối với thao tác rủi ro như chuyển tiền hoặc đóng tài khoản. Bài làm không kết nối hệ thống ngân hàng thật và chưa xây giao diện để con người phê duyệt thao tác.

### Red-team nhiều kỹ thuật

Năm kịch bản lần lượt thử điền chỗ trống, đổi định dạng, kể chuyện giả định, xác nhận thông tin và leo thang qua ba lượt hội thoại. Runtime lưu lịch sử theo user ID và session ID; kịch bản nhiều lượt lưu từng câu hỏi và câu trả lời trong `outputs/attack_results.json`.

Trong quá trình kiểm tra, phép đo leak có sẵn được phát hiện tính nhầm `password=[REDACTED]` là rò rỉ. Phép đo đã được sửa để chỉ báo leak khi có giá trị secret giả, kể cả trường hợp chèn ký tự phân cách. Artifact sau đó được sinh lại bằng lần chạy thật.

## 4. Kết quả kiểm tra

| Nội dung | Kết quả lần chạy cuối |
|---|---|
| Toàn bộ smoke/public/regression tests | 61 test đạt |
| Blue — câu an toàn | Cho qua 5/5 |
| Blue — câu tấn công | Chặn 7/7 |
| Blue — trường hợp biên | Chặn đầu vào rỗng; cho qua câu tiếng Việt và tài liệu ngân hàng hợp lệ |
| Spam qua toàn pipeline | 12 request: 10 được phép, 2 bị rate limit |
| Người dùng khác sau đợt spam | Vẫn được phục vụ |
| Red | 4/5 kịch bản có phản hồi chứa secret giả |
| Red Advance | 0/5 kịch bản leak; cả 5 bị chặn |
| Kiểm tra schema và đóng gói | Đạt; `technical_failure: false` |

Báo cáo tự động chỉ chạy lại nhóm public tests nên hiển thị 22 test; con số 61 là kết quả của lệnh chạy toàn bộ `tests`. Các số liệu trên là phạm vi kiểm thử của bài lab, chưa đủ để kết luận hệ thống an toàn trước mọi cách tấn công. Bài làm không tự quy đổi kết quả thành điểm hoặc bonus.

## 5. Nhận xét kỹ thuật

Red vẫn có thể cung cấp secret dù dùng model có năng lực cao hơn, vì system prompt của mục tiêu cố ý cho phép chia sẻ thông tin nội bộ. Do đó không thể chỉ dựa vào lựa chọn model để bảo vệ dữ liệu.

Các lớp phòng thủ có nhiệm vụ khác nhau: input filter giảm yêu cầu độc hại tới model; output filter giảm rò rỉ trong phản hồi; egress giới hạn nơi dữ liệu được gửi; rate limit giảm lạm dụng; audit giúp xem lại quyết định. Test tích hợp cần kiểm tra cả thứ tự các lớp và việc model có thực sự bị bỏ qua khi request bị chặn.

HITL chỉ có ý nghĩa khi quyết định của người duyệt được ghi nhận và kiểm tra tại nơi thực thi thao tác. Một câu trả lời của model nói rằng thao tác “đã được duyệt” không thay thế được approval có kiểm chứng.

## 6. Hướng phát triển và việc nộp bài

Các bước có thể mở rộng gồm kiểm thử thêm tiếng Việt và các dạng làm rối dữ liệu, đánh giá false positive với câu hỏi ngân hàng thực tế, kiểm thử nhiều request đồng thời và xây luồng HITL có người duyệt thật. Đây là hướng phát triển, chưa phải các khả năng đã được chứng minh trong lần chạy hiện tại.

Code và artifact đang ở máy local. Chưa commit/push, chưa đổi tên repo GitHub theo mẫu có `DAY11`, và chưa nộp link LMS. Trước khi nộp cần xác nhận cấu hình model được chấp nhận, kiểm tra lại thông tin cá nhân và hiểu được phần code có AI hỗ trợ.

## 7. Bằng chứng và cách chạy lại

- Phòng thủ: [results.json](outputs/results.json).
- Red-team và hội thoại nhiều lượt: [attack_results.json](outputs/attack_results.json).
- Quan sát: [audit_log.json](outputs/audit_log.json), [metrics.json](outputs/metrics.json).
- Báo cáo tự động: [lab_report.md](outputs/lab_report.md), [grade_report.json](outputs/grade_report.json).

```powershell
.\.venv312\Scripts\python.exe src/main.py
.\.venv312\Scripts\python.exe -m pytest tests -q
.\.venv312\Scripts\python.exe scripts/grade.py
```

Lệnh đầu gọi API thật và có thể phát sinh chi phí theo nhà cung cấp. Các file trong `outputs/` được sinh bởi chương trình; không sửa tay kết quả để thay đổi tỷ lệ chặn hoặc leak.
