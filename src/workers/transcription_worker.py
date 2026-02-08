import os
import json
import traceback
import torch
from PyQt5.QtCore import QThread, pyqtSignal

# שינוי קריטי: שימוש בספרייה הרשמית במקום בספרייה שקורסת
import whisper

class TranscriptionWorker(QThread):
    """Worker thread לתמלול קבצי MP3 באמצעות Whisper הרשמי"""
    progress_update = pyqtSignal(int)
    log_update = pyqtSignal(str)
    finished_success = pyqtSignal(str, list)
    finished_error = pyqtSignal(str)

    def __init__(self, audio_path, model_name="large", language="he", parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.model_name = model_name
        self.language = language

    def run(self):
        try:
            self.log_update.emit("מאתחל תהליך תמלול...")
            self.progress_update.emit(5)

            # כפיית שימוש ב-CPU ב-Mac למניעת בעיות MPS/Bus Error
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            device = "cpu"
            
            self.log_update.emit(f"טוען מודל: {self.model_name} (על {device})")
            
            # טעינת המודל הרשמי
            model = whisper.load_model(self.model_name, device=device)

            self.progress_update.emit(30)
            self.log_update.emit("מתחיל תמלול (זה עשוי לקחת זמן)...")

            # הגדרת שפה
            lang_param = None if self.language == "auto" else self.language

            # תמלול עם word_timestamps=True (התחליף הרשמי והיציב ל-whisper_timestamped)
            result = model.transcribe(
                self.audio_path,
                language=lang_param,
                verbose=False,
                fp16=False,       # חובה False ב-CPU כדי למנוע שגיאות
                word_timestamps=True # מאפשר דיוק ברמת מילה אם נצטרך בעתיד
            )

            self.progress_update.emit(80)
            self.log_update.emit("מעבד תוצאות...")

            # המרה לפורמט JSON
            karaoke_data = []
            index = 0

            # הקוד המקורי שלך השתמש ב-segments (רמת משפט). שמרתי על הלוגיקה הזו.
            for segment in result.get("segments", []):
                text = segment.get("text", "").strip()
                if not text:
                    continue

                start_ms = int(segment.get("start", 0) * 1000)
                end_ms = int(segment.get("end", 0) * 1000)

                karaoke_data.append({
                    "index": index,
                    "text": text,
                    "start": start_ms,
                    "end": end_ms,
                    "is_image": False
                })
                index += 1

            if not karaoke_data:
                self.finished_error.emit("התמלול הסתיים אך לא זוהה טקסט (אולי הקובץ שקט?).")
                return

            # שמירת JSON
            json_path = os.path.splitext(self.audio_path)[0] + ".json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(karaoke_data, f, ensure_ascii=False, indent=2)

            self.progress_update.emit(100)
            self.log_update.emit(f"תמלול הושלם! {len(karaoke_data)} קטעים זוהו.")
            self.finished_success.emit(json_path, karaoke_data)

        except Exception as e:
            tb = traceback.format_exc()
            self.finished_error.emit(f"שגיאה בתמלול: {str(e)}\n{tb}")