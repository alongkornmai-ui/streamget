import os
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

# สั่งให้บันทึกไฟล์ไว้ในโฟลเดอร์หลักของ Termux
UPLOAD_DIR = os.path.expanduser("~/received_files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
        <head><meta charset="utf-8"><title>Termux File Receiver</title></head>
        <body style="font-family: sans-serif; text-align: center; margin-top: 50px;">
            <h2>ระบบส่งไฟล์เข้า Termux ผ่านโดเมนส่วนตัว</h2>
            <form action="/upload" enctype="multipart/form-data" method="post" style="margin-top: 30px;">
                <input name="file" type="file" required style="padding: 10px; border: 1px solid #ccc;"><br><br>
                <input type="submit" value="เริ่มอัปโหลดไฟล์" style="padding: 10px 20px; background-color: #007bff; color: white; border: none; cursor: pointer;">
            </form>
        </body>
    </html>
    """

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())
    return {"status": "success", "message": f"บันทึกไฟล์ {file.filename} ลงใน Termux สำเร็จแล้ว!", "save_path": file_path}

if __name__ == "__main__":
    # รันพอร์ต 8000 ให้ตรงตามที่ผูกไว้กับ Cloudflare Tunnel
    uvicorn.run(app, host="127.0.0.1", port=8000)
