import re
import unicodedata

def remove_nikud(text):
    """מסירה את כל סימני הניקוד מהטקסט"""
    if not text: return ""
    normalized = unicodedata.normalize('NFKD', text)
    return "".join([c for c in normalized if not unicodedata.combining(c)])

def advanced_cleanup(text):
    """ניקוי כללי של תווים לא רצויים וסידור רווחים"""
    if not text: return ""
    # הסרת תווים בלתי נראים (LTR/RTL marks)
    text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', text)
    # צמצום רווחים כפולים
    text = re.sub(r' +', ' ', text)
    return text.strip()