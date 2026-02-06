import re
import time
import requests
import unicodedata
import concurrent.futures
from PyQt5.QtCore import QThread, pyqtSignal

class NikudWorker(QThread):
    finished = pyqtSignal(str) 
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    progress_percent = pyqtSignal(int)

    def __init__(self, text, nikud_dict=None):
        super().__init__()
        self.text = text
        self.nikud_dict = nikud_dict if nikud_dict else {}
        self.metadata = {} # יוזרק מבחוץ
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=3)
        self.session.mount('https://', adapter)

    def run(self):
        print(f"\n[DEBUG] === Starting NikudWorker ===")
        print(f"[DEBUG] Text length: {len(self.text)} chars")
        
        # === שלב 1: הגנה על תגיות תמונה ===
        # מחליפים את כל התגיות [IMG:...] בטוקן זמני כדי שהניקוד והמילון לא ייגעו בהן
        protected_imgs = {}
        
        def replace_callback(match):
            # יוצר טוקן ייחודי, למשל: __IMG_PROTECTED_0__
            token = f"__IMG_PROTECTED_{len(protected_imgs)}__"
            protected_imgs[token] = match.group(0) # שומר את התגית המקורית בצד
            return token
            
        # יצירת טקסט זמני שבו התמונות מוחלפות בטוקנים
        temp_text = re.sub(r'\[IMG:.*?\]', replace_callback, self.text)
        # ===================================

        try:
            self.progress.emit("שולח את הטקסט המלא לניקוד (דיקטה)...")
            
            t0 = time.time()
            # שולחים את הטקסט המוגן (עם הטוקנים, בלי הנתיבים) לניקוד
            vocalized_text = self.full_text_vocalization_process(temp_text)
            dt = time.time() - t0
            print(f"[DEBUG] Dicta process finished in {dt:.2f} seconds.")
            
            self.progress.emit("מחיל הגדרות מילון אישי...")
            print(f"[DEBUG] Applying dictionary replacements ({len(self.nikud_dict)} items)...")
            
            # החלפת מילים מהמילון (עדיין על הטקסט עם הטוקנים)
            final_text = self.apply_dictionary_on_vocalized(vocalized_text)
            
            # === שלב 2: שחזור תגיות תמונה ===
            # מחזירים את התגיות המקוריות למקומן במקום הטוקנים
            for token, original_tag in protected_imgs.items():
                final_text = final_text.replace(token, original_tag)
            # ================================
            
            print(f"[DEBUG] NikudWorker finished successfully.")
            self.progress.emit("סיום עיבוד.")
            self.finished.emit(final_text)

        except Exception as e:
            print(f"[DEBUG] CRITICAL ERROR in NikudWorker: {e}")
            import traceback
            traceback.print_exc()
            
            self.progress.emit("שגיאה")
            self.error.emit(str(e))
            
            # במקרה חירום משחזרים את הטקסט המקורי (הלא מנוקד) כדי לא לאבד מידע
            self.finished.emit(self.text)

    def clean_non_bgdkpt(self, text):
        if not text: return ""
        allowed_dagesh = ['\u05d1', '\u05db', '\u05e4', '\u05d5'] 
        dagesh_char = '\u05bc'
        chars = list(text)
        out = []
        for i, char in enumerate(chars):
            if char == dagesh_char:
                if i > 0 and chars[i-1] in allowed_dagesh:
                    out.append(char)
            else:
                out.append(char)
        return "".join(out)

    def vocalize_batch(self, word_list):
        if not word_list: return []
        
        # הדפסה שתראה איזה באצ' נשלח כרגע
        sample = word_list[0] if word_list else ""
        print(f"[DEBUG] Sending batch of {len(word_list)} words (Starts with: {sample})...")
        
        text_to_send = " ".join(word_list)
        try:
            url = "https://nakdan-2-0.loadbalancer.dicta.org.il/api"
            payload = {
                "task": "nakdan", "data": text_to_send, "genre": "modern", 
                "keepqq": False, "nodageshdefekt": False, "kamatzdefekt": False, 
                "allways": False, "optimizer": True
            }
            headers = {'Content-Type': 'application/json;charset=UTF-8'}
            
            # הוספתי Timeout כדי שלא ייתקע לנצח
            response = self.session.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                result_words = []
                if isinstance(data, list):
                    for token in data:
                        word = token.get('word', '')
                        if 'options' in token and token['options']:
                            word = token['options'][0].replace('|', '').strip()
                        word = self.clean_non_bgdkpt(word)
                        if word.strip():
                            result_words.append(word)
                
                if len(result_words) == len(word_list):
                    print(f"[DEBUG] Batch success.")
                    return result_words
                
                print(f"[DEBUG] Batch mismatch! Sent {len(word_list)}, got {len(result_words)}. Fallback to single words.")
                # Fallback code...
                fixed_words = []
                # כאן לא נוסיף הדפסות כדי לא להציף, אבל זה ירוץ במקביל
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    fixed_words = list(executor.map(self.vocalize_single_word, word_list))
                return fixed_words

            else:
                print(f"[DEBUG] Server Error: {response.status_code}")

        except Exception as e:
            print(f"[DEBUG] Batch Exception: {e}")
        
        return word_list

    def vocalize_single_word(self, word):
        # ... (אותו קוד כמו מקודם) ...
        try:
            url = "https://nakdan-2-0.loadbalancer.dicta.org.il/api"
            payload = {"task": "nakdan", "data": word, "genre": "modern", "optimizer": True}
            headers = {'Content-Type': 'application/json;charset=UTF-8'}
            response = self.session.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data and 'options' in data[0]:
                    return self.clean_non_bgdkpt(data[0]['options'][0].replace('|', '').strip())
        except: pass
        return word

    def full_text_vocalization_process(self, input_text):
        print("[DEBUG] Pre-processing text for batching...")
        parts = re.split(r'([^\u0590-\u05FF]+)', input_text)
        
        indices_to_process = []
        words_to_process = []
        
        for i, part in enumerate(parts):
            if any('\u0590' <= c <= '\u05FF' for c in part):
                indices_to_process.append(i)
                words_to_process.append(part)

        total_words = len(words_to_process)
        print(f"[DEBUG] Total Hebrew words to vocalize: {total_words}")
        
        BATCH_SIZE = 100
        batches = []
        for i in range(0, total_words, BATCH_SIZE):
            batches.append((words_to_process[i : i + BATCH_SIZE], indices_to_process[i : i + BATCH_SIZE]))
        
        completed_batches = 0
        total_batches = len(batches)
        print(f"[DEBUG] Created {total_batches} batches. Sending to thread pool...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_batch = {executor.submit(self.vocalize_batch, b[0]): b[1] for b in batches}
            
            for future in concurrent.futures.as_completed(future_to_batch):
                indices = future_to_batch[future]
                try:
                    res_words = future.result()
                    # שילוב התוצאות
                    for idx_in_parts, word in zip(indices, res_words):
                        parts[idx_in_parts] = word
                except Exception as e:
                    print(f"[DEBUG] Future Error: {e}")
                
                completed_batches += 1
                percent = int((completed_batches / total_batches) * 90)
                self.progress_percent.emit(percent)
                if completed_batches % 5 == 0:
                    print(f"[DEBUG] Progress: {completed_batches}/{total_batches} batches done.")

        print("[DEBUG] Reassembling full text...")
        return "".join(parts)

    def apply_dictionary_on_vocalized(self, text):
        sorted_keys = sorted(self.nikud_dict.keys(), key=len, reverse=True)
        processed_text = text

        for base_word in sorted_keys:
            target_vocalization = self.nikud_dict[base_word]
            
            # בדיקת סוג התאמה
            is_exact = False
            if hasattr(self, 'metadata') and base_word in self.metadata:
                if self.metadata[base_word].get('match_type') == 'exact':
                    is_exact = True

            word_pattern = self.get_vocalized_pattern(base_word)
            
            if is_exact:
                # Lookbehind & Lookahead
                full_regex = r'(?<![\w\u0590-\u05FF])' + word_pattern + r'(?![\w\u0590-\u05FF])'
                processed_text = re.sub(full_regex, target_vocalization, processed_text)
            else:
                # Partial
                processed_text = re.sub(word_pattern, target_vocalization, processed_text)
                
        return processed_text

    def get_vocalized_pattern(self, base_word):
        pattern = ""
        for char in base_word:
            pattern += re.escape(char) + r'[\u0591-\u05C7]*'
        return pattern
    