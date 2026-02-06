import re
import unicodedata

# --- לוגיקה חכמה לטיפול בתחיליות (משה וכלב) ---
def apply_smart_replacement(text, base_word, target_vocalization):
    """
    מחליפה את base_word ב-target_vocalization בתוך הטקסט,
    תוך התעלמות (ושימור) של תחיליות כמו ו', ה', ב', ל' וכו'.
    """
    word_pattern = ""
    for char in base_word:
        word_pattern += re.escape(char) + r'[\u0591-\u05C7]*'

    prefix_pattern = r'([משוהכלב][\u0591-\u05C7]*)*'
    full_regex = r'(?<![\w\u0590-\u05FF])(' + prefix_pattern + ')' + word_pattern + r'(?![\w\u0590-\u05FF])'

    return re.sub(full_regex, r'\1' + target_vocalization, text)

def clean_non_bgdkpt(text):
    """מסירה דגשים שאינם בגדכפ''ת (משמש את הניקוד)"""
    if not text: return ""
    allowed_dagesh = ['\u05d1', '\u05db', '\u05e4', '\u05d5'] # ב, כ, פ, ו
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

def remove_nikud(text):
    normalized = unicodedata.normalize('NFD', text)
    return "".join([c for c in normalized if not unicodedata.combining(c)])

def advanced_cleanup(self, text):
        """
        פונקציית עזר לתיקון בעיות נפוצות בייבוא PDF בעברית
        """
        # 1. איחוד רווחים כפולים
        text = re.sub(r'\s+', ' ', text)
        
        # 2. תיקון רווח לפני נקודה/פסיק (לדוגמה: "מילה ." -> "מילה.")
        text = re.sub(r'\s+([.,?!:;])', r'\1', text)

        # 3. החזרת ירידות שורה אחרי נקודות (כדי שלא הכל יהיה גוש אחד)
        # מחפש נקודה שאחריה רווח ואות, והופך לירידת שורה כפולה
        text = re.sub(r'\. ([א-ת])', r'.\n\n\1', text)

        # 4. תיקון סוגריים באנגלית שהתבלגנו (הבעיה הספציפית שהייתה לך)
        # דוגמה: הופך את "Absorption ,(" ל- "(Absorption),"
        # מזהה מילה באנגלית, אחריה רווח אופציונלי, פסיק וסוגר פותח
        text = re.sub(r'([a-zA-Z\-\s]+)\s*,?\(', r'(\1), ', text)
        
        # תיקון נוסף: "Word (" -> "(Word)"
        # במקרים שאין פסיק
        text = re.sub(r'([a-zA-Z]+)\s+\(', r'(\1) ', text)

        # 5. תיקון ספציפי לבעיות צירים (מהדוגמה שלך)
        text = text.replace("בציר ה־ אנו", "בציר ה־X אנו")
        text = text.replace("ובציר ה־ את", "ובציר ה־Y את")
        
        # 6. החזרת תגיות PAGE להיות בשורה נפרדת (כי הניקוי אולי חיבר אותן)
        text = re.sub(r'(\[PAGE:\d+\])', r'\n\n\1\n', text)

        return text


def merge_nikud_preserving_spaces(original_text, nikud_tokens):
    """
    ממזג את רשימת המילים המנוקדות (nikud_tokens) לתוך הטקסט המקורי,
    תוך שמירה קפדנית על רווחים, ירידות שורה וסימני פיסוק מהמקור.
    """
    # יצירת תור של מילים מנוקדות
    tokens_queue = list(nikud_tokens)
    tokens_index = 0
    
    # פיצול הטקסט המקורי לפי מילים עבריות, תוך שמירה על המפרידים (רווחים וכו')
    # הביטוי הרגולרי תופס רצף של אותיות עבריות או רצף של תווים שאינם עברית
    parts = re.split(r'([\u0590-\u05FF]+)', original_text)
    
    final_output = []
    
    for part in parts:
        if not part: continue
        
        # אם החלק הוא מילה בעברית (לפי טווח יוניקוד)
        if re.match(r'[\u0590-\u05FF]+', part):
            # אנחנו צריכים למצוא את המילים המנוקדות שמרכיבות את המילה הזו
            # (לפעמים דיקטה מפצל מילה כמו "וכשבבית" ל-"ו", "כש", "ב", "בית")
            
            built_word = ""
            base_letters_count = 0
            target_length = len(part) # אורך המילה המקורית (ללא ניקוד כי היא מהמקור)
            
            while base_letters_count < target_length and tokens_index < len(tokens_queue):
                next_token = tokens_queue[tokens_index]
                tokens_index += 1
                
                built_word += next_token
                
                # בדיקה כמה אותיות בסיס יש בטוקן הזה כדי לדעת מתי עברנו את המילה המקורית
                clean_token = "".join([c for c in next_token if 'א' <= c <= 'ת'])
                base_letters_count += len(clean_token)
            
            final_output.append(built_word)
        else:
            # אם זה רווח, ירידת שורה, פסיק או אנגלית - שומרים כמו שהוא
            final_output.append(part)
            
    return "".join(final_output)