# Ô ăn quan online — bản sửa quân quan và hiệu ứng rải

## Cấu trúc
- `server.py`: máy chủ FastAPI/WebSocket; trạng thái quân dân và hai quân quan được lưu riêng.
- `static/index.html`: giao diện, chơi với máy và hiệu ứng rải quân.
- `requirements.txt`, `render.yaml`: cấu hình chạy trên Render.

## Các điểm đã sửa
- Hai quân quan là vật thể riêng biệt (`quan_alive`), hiển thị bằng viên đá lớn màu vàng. Số quân dân trong ô quan được đếm riêng và vẫn là đá nhỏ cùng kiểu với quân dân ở các ô khác.
- Quân dân được rải vào ô quan không làm biến đổi hình dáng hoặc bản chất của quân quan.
- Hàng dưới là Người chơi 1; hàng trên là Người chơi 2 / máy tính.
- Tô sáng ô đang chọn, làm nổi hàng của người đang đi và hiện thông báo lượt.
- Chuyển động rải được gửi từng khung hình từ máy chủ, khoảng 0,32 giây mỗi quân; máy tính đợi khoảng 0,9 giây trước khi đi.
- Logic chơi với máy dùng cùng mô hình quân quan tách biệt.
- Giữ số ván thắng tích lũy trong phòng; điểm mỗi ván được đặt lại khi chơi ván mới.

## Chạy thử trên máy
```bash
python -m pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000
```
Mở `http://127.0.0.1:8000`.

## Cập nhật trên GitHub/Render
Giải nén gói ZIP, thay `server.py`, thay `static/index.html` và giữ nguyên cấu trúc thư mục. Commit thay đổi rồi vào Render → Manual Deploy → Deploy latest commit.
