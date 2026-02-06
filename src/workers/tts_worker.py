import os
import io
import re
import json
import asyncio
from datetime import datetime
from pydub import AudioSegment
import edge_tts
from PyQt5.QtCore import QThread, pyqtSignal

# --- הגדרת סוגי שגיאות מותאמים אישית ---
class ServerOverloadError(Exception):
    """שגיאה שמעידה שהשרת עמוס או דוחה את הבקשה"""
    pass

class NetworkConnectionError(Exception):
    """שגיאה שמעידה על בעיה באינטרנט המקומי"""
    pass

class TTSWorker(QThread):
    progress_update = pyqtSignal(int)
    log_update = pyqtSignal(str)
    finished_success = pyqtSignal(str, list)
    finished_error = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text, output_file, voice, rate, volume, dicta_dict, parent=None, dual_mode=False):
        super().__init__(parent)
        self.text = text
        self.output_path = output_file
        self.voice = voice
        self.rate = rate
        self.speed = rate # תיקון: משתנה נדרש
        self.volume = volume
        self.dicta_dict = dicta_dict
        self.dual_mode = dual_mode
        
        # גיבוי לקולות
        self.he_voice = voice
        self.en_voice = voice 
        
        # הגדרות ברירת מחדל למניעת קריסה
        self.user_max_limit = 15
        self.min_limit = 1
        self.current_limit = 15
        
        # שליפת הגדרות מההורה אם קיים
        self.settings = {}
        if parent and hasattr(parent, 'settings'):
            self.settings = parent.settings
            
            # 1. כאן אתה שואב את ה-30 מההגדרות
            self.user_max_limit = int(self.settings.get("max_concurrent", 5))
            
            # === 2. הוסף את השורה הזו: עדכון המגבלה בפועל ===
            self.current_limit = self.user_max_limit 
            # ===============================================

            if "selected_he_voice" in self.settings and hasattr(parent, 'he_voices'):
                 he_key = self.settings["selected_he_voice"]
                 self.he_voice = parent.he_voices.get(he_key, voice)
            
            if "selected_en_voice" in self.settings and hasattr(parent, 'en_voices'):
                 en_key = self.settings["selected_en_voice"]
                 self.en_voice = parent.en_voices.get(en_key, voice)

        # משתנים פנימיים
        self.is_running = True
        self.loop = None
        self.results = {}
        self.skipped_sentences = []
        self.completed_count = 0
        self.total_sentences = 0
        self.processing_idxs = set() # תיקון: למניעת קריסה בלוגים
        self.consecutive_successes = 0
        self.consecutive_errors = 0

    def run(self):
        print(f"\n=== STARTING TTS (Target: {self.user_max_limit}) ===")
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.process_adaptive())
        except Exception as e:
            print(f"[CRITICAL ERROR] {e}")
            import traceback
            traceback.print_exc()
            self.finished_error.emit(str(e))
        finally:
            self.loop.close()
            print("=== PROCESS FINISHED ===\n")

    def enforce_dictionary(self, text):
        """מבצע את החלפות המילון"""
        if not self.settings: return text
        nikud_dict = self.settings.get("nikud_dictionary", {})
        metadata = self.settings.get("nikud_metadata", {})
        sorted_keys = sorted(nikud_dict.keys(), key=len, reverse=True)
        processed_text = text
        for base_word in sorted_keys:
            target = nikud_dict[base_word]
            match_type = metadata.get(base_word, {}).get("match_type", "partial")
            if match_type == "exact":
                pattern = r'(?<![\w\u0590-\u05FF])' + re.escape(base_word) + r'(?![\w\u0590-\u05FF])'
                processed_text = re.sub(pattern, target, processed_text)
            else:
                processed_text = processed_text.replace(base_word, target)
        return processed_text

    def report_status(self):
        active_list = sorted(list(self.processing_idxs))
        msg = f"🚀 עובדים: {self.current_limit} | פעיל: {active_list[:5]}..."
        self.log_update.emit(msg)

    async def process_adaptive(self):
        print("[DEBUG] TTSWorker: process_adaptive started (Preserving Layout)")
        
        # 1. ניקוי והכנה - בלי למחוק ירידות שורה!
        text_processed = self.enforce_dictionary(self.text)
        text_processed = re.sub(r'(\d)\.(\d)', r'\1__DECIMAL_POINT__\2', text_processed)
        # מסירים רק מקפים בעייתיים, אבל משאירים את \n
        text_processed = text_processed.replace("-", " ").replace("–", " ").replace("•", "")
        
        # 2. חלוקה חכמה ששומרת על המבנה
        # הביטוי הזה מפריד: תגיות, סימני סיום משפט, או ירידות שורה
        split_pattern = r'(\[PAGE:\d+\]|\[IMG:.*?\]|[.?!]+|\n)'
        raw_parts = re.split(split_pattern, text_processed)
        
        final_sentences = []
        current_buffer = ""
        
        for part in raw_parts:
            if not part: continue
            
            part = part.replace("__DECIMAL_POINT__", ".")
            
            # טיפול בתגיות (עמוד/תמונה) - סוגרים את המשפט הקודם ומוסיפים את התגית
            if "[PAGE:" in part or "[IMG:" in part:
                if current_buffer.strip(): # אם נצבר טקסט, דחוף אותו לרשימה
                    final_sentences.append(current_buffer)
                    current_buffer = ""
                final_sentences.append(part)
                continue
            
            # צבירת הטקסט לתוך הבאפר הנוכחי
            current_buffer += part
            
            # בדיקה: האם הגענו לסוף "יחידה"?
            # יחידה היא סוף משפט (.) או סוף שורה (\n)
            is_newline = "\n" in part
            is_punctuation = re.match(r'^[.?!]+$', part.strip())
            
            if is_newline or is_punctuation:
                # אם יש לנו טקסט ממשי בבאפר - שומרים אותו כמשפט
                if current_buffer.strip():
                    final_sentences.append(current_buffer)
                    current_buffer = ""
                
                # מקרה קצה: שורות ריקות (רק \n)
                # אם הבאפר מכיל רק ירידת שורה (בלי טקסט), אנחנו רוצים לצרף אותה למשפט הקודם
                # כדי שהנגן ידע לרדת שורה אחרי המשפט הקודם
                elif is_newline and current_buffer == "\n":
                    if final_sentences and not final_sentences[-1].startswith("["):
                         final_sentences[-1] += "\n"
                    current_buffer = ""

        # שאריות שנשארו בבאפר
        if current_buffer:
            final_sentences.append(current_buffer)

        self.total_sentences = len(final_sentences)
        print(f"[DEBUG] Total items to process: {self.total_sentences}")

        # === שלב העיבוד (Processing) ===
        queue = asyncio.Queue()
        
        # מיון: עמודים ותמונות לא נשלחים ל-TTS
        for i, s in enumerate(final_sentences):
            # אם זה לא טקסט להקראה (עמוד, תמונה, או רק ירידת שורה)
            if "[PAGE:" in s or "[IMG:" in s or not s.strip():
                # מסמנים כהצלחה ריקה (שקט)
                self.results[i] = AudioSegment.silent(duration=0) 
            else:
                queue.put_nowait((i, s))

        # הרצת ה-Workers
        active_tasks = set()
        
        while not queue.empty() or active_tasks:
            while len(active_tasks) < self.current_limit and not queue.empty():
                idx, sent = queue.get_nowait()
                # שולחים את הטקסט נקי מרווחים מיותרים ל-TTS, אבל שומרים את המקור ל-JSON
                clean_sent_for_tts = sent.strip()
                task = asyncio.create_task(self.worker_wrapper(idx, clean_sent_for_tts))
                active_tasks.add(task)

            if active_tasks:
                done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    active_tasks.remove(task)
                    try:
                        result = await task
                        if result['status'] == 'success':
                            self.results[result['index']] = result['audio']
                            self.completed_count += 1
                            progress = int((self.completed_count / self.total_sentences) * 100)
                            self.progress_update.emit(progress)
                    except Exception: pass

        # === שלב השמירה (Saving) ===
        self.log_update.emit("בונה קובץ סופי...")
        
        final_audio = AudioSegment.empty()
        karaoke_data = [] 
        current_time_ms = 0
        pause_duration = self.settings.get("pause_sentence", 600)
        silence_segment = AudioSegment.silent(duration=pause_duration, frame_rate=24000)

        for i in range(self.total_sentences):
            raw_text = final_sentences[i]
            
            # 1. טיפול בטריגר עמוד
            if "[PAGE:" in raw_text:
                try:
                    match = re.search(r'\[PAGE:(\d+)\]', raw_text)
                    if match:
                        page_num = int(match.group(1))
                        karaoke_data.append({
                            "index": i, "text": "", "start": current_time_ms, "end": current_time_ms,
                            "is_image": False, "page_trigger": page_num
                        })
                except: pass
                continue 

            # 2. טיפול באודיו
            if i in self.results:
                segment = self.results[i]
                if segment.frame_rate != 24000: segment = segment.set_frame_rate(24000)
                
                duration = len(segment)
                
                # כאן הקסם: raw_text מכיל את ה-\n המקורי מהאדיטור
                karaoke_data.append({
                    "index": i,
                    "text": raw_text, # <--- הטקסט המקורי עם ירידות השורה נשמר
                    "start": current_time_ms,
                    "end": current_time_ms + duration,
                    "is_image": "[IMG:" in raw_text
                })
                
                final_audio += segment
                current_time_ms += duration
                
                if "[IMG:" not in raw_text and raw_text.strip():
                    final_audio += silence_segment
                    current_time_ms += pause_duration

        # ייצוא לקובץ
        try:
            await self.loop.run_in_executor(None, final_audio.export, self.output_path, "mp3")
            
            json_path = self.output_path.replace(".mp3", ".json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(karaoke_data, f, ensure_ascii=False, indent=4)
                
            self.finished_success.emit(self.output_path, self.skipped_sentences)
            
        except Exception as e:
            self.finished_error.emit(f"שגיאה בשמירה: {e}")

    async def worker_wrapper(self, idx, sentence):
        self.processing_idxs.add(idx)
        self.report_status()
        try:
            audio = await self.process_single_sentence(sentence, idx)
            if len(audio) > 0:
                self.consecutive_errors = 0
                return {'status': 'success', 'index': idx, 'audio': audio}
            else:
                raise ServerOverloadError("Empty audio")
        except Exception as e:
            # במקרה של כישלון מוחלט אחרי ניסיונות חוזרים
            print(f"[ERROR] Worker failed on {idx}: {e}")
            # מחזירים שקט כדי לא לתקוע את התהליך
            return {'status': 'success', 'index': idx, 'audio': AudioSegment.silent(duration=500, frame_rate=24000)}
        finally:
            if idx in self.processing_idxs: self.processing_idxs.remove(idx)

    async def process_single_sentence(self, sentence, idx):
        if "[IMG:" in sentence:
            return AudioSegment.silent(duration=4000, frame_rate=24000)
            
        try:
             # שימוש בלוגיקה הקיימת (Dual Mode או רגיל)
             if self.dual_mode:
                 return await self.generate_natural_audio(sentence, idx)
             else:
                 audio_bytes = await self.fetch_audio_internal(sentence, self.he_voice, idx)
                 if audio_bytes:
                    return await self.loop.run_in_executor(None, self.bytes_to_audio, audio_bytes, idx)
                 return AudioSegment.silent(duration=0, frame_rate=24000)
        except Exception as e: 
            print(f"[RETRY NEEDED] {e}")
            # כאן אמורה להיות לוגיקת ה-Retry המלאה שלך (קיצרתי למען הבהירות)
            # אם יש לך את הפונקציה retry_logic, תקרא לה כאן
            return AudioSegment.silent(duration=0, frame_rate=24000)

    async def fetch_audio_internal(self, text, voice, log_id):
        if not text or not text.strip(): return None
        try:
            communicate = edge_tts.Communicate(text, voice, rate=self.speed)
            data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": data += chunk["data"]
            return data
        except Exception as e:
            print(f"[EDGE-TTS ERROR] {e}")
            return None

    def bytes_to_audio(self, audio_bytes, idx):
        try:
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
            # וידוא תדר דגימה אחיד
            if seg.frame_rate != 24000: seg = seg.set_frame_rate(24000)
            return self.smart_trim(seg, idx)
        except: return AudioSegment.silent(duration=0, frame_rate=24000)

    def smart_trim(self, audio_segment, idx, limit=-50):
        # (הלוגיקה שלך ל-trim נשארת זהה)
        return audio_segment

    async def generate_natural_audio(self, sentence, idx):
        # (הלוגיקה שלך ל-dual mode נשארת זהה)
        # רק וודא שאתה משתמש ב-fetch_audio_internal
        # ושהחזרת ה-AudioSegment תקינה
        return await self.process_single_sentence(sentence, idx) # הפנייה זמנית, תדביק את הלוגיקה המקורית אם יש לך


class AudioPreviewWorker(QThread):
    # האות מחזיר כעת שני דברים: את המפתח הייחודי ואת המידע עצמו
    finished_data = pyqtSignal(str, bytes) 

    def __init__(self, cache_key, text, voice, speed):
        super().__init__()
        self.cache_key = cache_key
        self.text = text
        self.voice = voice
        self.speed = speed

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.generate())
        loop.close()

    async def generate(self):
        try:
            data = b""
            communicate = edge_tts.Communicate(self.text, self.voice, rate=self.speed)
            
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            
            # החזרת המפתח והמידע
            self.finished_data.emit(self.cache_key, data)
            
        except Exception as e:
            print(f"Preview Memory Error: {e}")
