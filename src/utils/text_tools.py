import re
import unicodedata

def remove_nikud(text):
    """מסירה את כל סימני הניקוד מהטקסט"""
    if not text: return ""
    normalized = unicodedata.normalize('NFKD', text)
    return "".join([c for c in normalized if not unicodedata.combining(c)])

def cleanup_pdf_page(page_text):
    """ניקוי טקסט של עמוד בודד מ-PDF (מותאם ל-pdfplumber layout mode)"""
    if not page_text:
        return ""
    # הסרת תווים בלתי נראים (LTR/RTL marks)
    page_text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', page_text)
    # סינון שורות שהן רק מספרי עמוד בודדים
    lines = page_text.split('\n')
    filtered = [l for l in lines if not re.match(r'^\s*\d+\s*$', l.strip())]
    page_text = '\n'.join(filtered)
    # תיקון סימני פיסוק RTL: ב-PDF עברי, סימני פיסוק מופיעים לפעמים בתחילת השורה
    # דבוקים למילה (למשל ".פינוייה" במקום "פינוייה.")
    lines = page_text.split('\n')
    lines = [re.sub(r'^([.!?,;:"\u05F4]+)(\S+)', r'\2\1', l) for l in lines]
    # תיקון סדר גרשיים-נקודה: word." -> word".
    lines = [re.sub(r'\.(")', r'\1.', l) for l in lines]
    page_text = '\n'.join(lines)
    # צמצום רווחים כפולים בתוך שורות
    page_text = re.sub(r' +', ' ', page_text)
    # צמצום שורות ריקות מרובות
    page_text = re.sub(r'\n{3,}', '\n\n', page_text)
    return page_text.strip()


def advanced_cleanup(text):
    """ניקוי כללי של תווים לא רצויים וסידור רווחים"""
    if not text: return ""
    # הסרת תווים בלתי נראים (LTR/RTL marks)
    text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text)
    # צמצום רווחים כפולים
    text = re.sub(r' +', ' ', text)
    # צמצום שורות ריקות מרובות
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()