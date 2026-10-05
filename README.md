# Lịch sử tương tác và tấn công phi kỹ thuật giữa các agent LLM

[English](README.en.md)

Chương trình chạy một thí nghiệm hai giai đoạn giữa các agent LLM. Ở giai đoạn tạo lịch sử thì các agent trò chuyện về công việc chung của một dự án. Ở giai đoạn tấn công thì bên gửi xin token deploy staging mà agent mục tiêu đang giữ theo chính sách chia sẻ theo vai trò. Chương trình đo tỷ lệ token bị lộ khi agent mục tiêu nhớ các buổi trò chuyện trước với bên gửi (B), khi các buổi đó gắn với một tên khác (A) và khi chúng không được đưa vào bước truy hồi (C).

## Yêu cầu

Python 3.9 trở lên, chỉ dùng thư viện chuẩn. Mô hình được gọi qua HTTP bằng Gemini API hoặc DeepSeek API.

## Cách chạy

`py pilot.py -h` liệt kê các lệnh. Mỗi script có ghi cách dùng ở mấy dòng đầu.

`py pilot.py selftest` chạy toàn bộ quy trình trên một mô hình giả trong thư mục tạm, không cần khóa API.

## Khóa API

Copy `.env.example` thành `.env` rồi dán khóa vào đó. `.env` nằm trong `.gitignore`. 

## Dữ liệu

Các thư mục dữ liệu (`data-*/`) không có trong repo. Chúng chứa lịch sử, bản ghi được truy hồi, phản hồi và kết quả chấm của từng lượt, tức bộ cuộc trò chuyện giữa các agent.

## Các lần chạy chính

| Bộ dữ liệu | Ngày chạy | Commit |
|---|---|---|
| Gemini (`gemini-3.5-flash-lite`) | 04/10/2026 | `ebd3c79` |
| DeepSeek (`deepseek-flash`) | 05/10/2026 | `30fe0b0` |

Mã băm script trong log được tính trên bản checkout ở Windows với kiểu xuống dòng CRLF, nên bản clone mới có thể cho mã băm khác dù nội dung giống nhau.
