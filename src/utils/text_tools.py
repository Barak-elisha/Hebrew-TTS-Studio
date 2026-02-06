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
    # איחוד שורות שבורות מ-PDF (כל מילה בשורה נפרדת) לפסקאות
    # שומר על שורות ריקות כמפרידי פסקאות ועל תגיות [PAGE:X]
    lines = text.split('\n')
    merged_lines = []
    current_paragraph = []
    for line in lines:
        stripped = line.strip()
        # שורה ריקה או תגית עמוד = מפריד פסקה
        if not stripped or re.match(r'\[PAGE:\d+\]', stripped):
            if current_paragraph:
                merged_lines.append(' '.join(current_paragraph))
                current_paragraph = []
            merged_lines.append(stripped)
        else:
            current_paragraph.append(stripped)
    if current_paragraph:
        merged_lines.append(' '.join(current_paragraph))
    text = '\n'.join(merged_lines)
    # צמצום רווחים כפולים
    text = re.sub(r' +', ' ', text)
    # צמצום שורות ריקות מרובות
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()