import os
import requests
from PyQt5.QtCore import QThread, pyqtSignal

class TelegramWorker(QThread):
    finished = pyqtSignal()
    upload_progress = pyqtSignal(int)
    log_update = pyqtSignal(str)

    def __init__(self, token, chat_id, files_list):
        """
        files_list: רשימה של טאפלים [(path, type), ...]
        type יכול להיות 'audio' או 'document'
        """
        super().__init__()
        self.token = token
        self.chat_id = chat_id
        self.files_list = files_list

    def run(self):
        print(f"\n--- [DEBUG] Starting Batch Telegram Upload ---")
        
        total_files = len(self.files_list)
        
        for index, (file_path, msg_type) in enumerate(self.files_list):
            if not file_path or not os.path.exists(file_path):
                continue

            filename = os.path.basename(file_path)
            self.log_update.emit(f"שולח לטלגרם ({index+1}/{total_files}): {filename}...")

            # הגדרת סוג השליחה (אודיו או מסמך)
            if msg_type == 'audio':
                endpoint = "sendAudio"
                field_name = "audio"
            else:
                endpoint = "sendDocument"
                field_name = "document"

            url = f"https://api.telegram.org/bot{self.token}/{endpoint}"
            boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
            
            # קידוד שם הקובץ
            filename_header = filename.replace('"', '\\"')
            
            # הכנת ה-Header
            part_boundary = f'--{boundary}\r\n'.encode('utf-8')
            end_boundary = f'\r\n--{boundary}--\r\n'.encode('utf-8')
            
            payload_meta = []
            payload_meta.append(part_boundary)
            payload_meta.append(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{self.chat_id}\r\n'.encode('utf-8'))
            
            # Caption (רק לקובץ הראשון או לכולם, לבחירתך. כאן שמנו רק לאודיו)
            if msg_type == 'audio':
                payload_meta.append(part_boundary)
                payload_meta.append(f'Content-Disposition: form-data; name="caption"\r\n\r\nHebrew TTS Studio\r\n'.encode('utf-8'))
            
            # File Header
            payload_meta.append(part_boundary)
            header_str = f'Content-Disposition: form-data; name="{field_name}"; filename="{filename_header}"\r\n'
            payload_meta.append(header_str.encode('utf-8'))
            
            # קביעת MIME Type
            mime_type = "audio/mpeg" if msg_type == 'audio' else "application/pdf"
            payload_meta.append(f'Content-Type: {mime_type}\r\n\r\n'.encode('utf-8'))
            
            header_bytes = b''.join(payload_meta)
            file_size = os.path.getsize(file_path)
            total_packet_size = len(header_bytes) + file_size + len(end_boundary)
            
            # פונקציית Streaming
            def data_generator():
                yield header_bytes
                bytes_sent = 0
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192 * 4)
                        if not chunk: break
                        yield chunk
                        bytes_sent += len(chunk)
                        
                        # חישוב אחוזים יחסי לקובץ הנוכחי בתוך התהליך הכולל
                        file_percent = (bytes_sent / file_size)
                        total_percent = int(((index + file_percent) / total_files) * 100)
                        self.upload_progress.emit(total_percent)
                yield end_boundary

            try:
                headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
                response = requests.post(url, data=data_generator(), headers=headers, timeout=300)
                
                if response.status_code != 200:
                    self.log_update.emit(f"שגיאה בשליחת {filename}: {response.status_code}")
                    print(f"[ERROR] Telegram Response: {response.text}")
            except Exception as e:
                self.log_update.emit(f"תקלה בשליחה: {str(e)}")

        self.upload_progress.emit(100)
        self.finished.emit()
