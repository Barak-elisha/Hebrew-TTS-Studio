import re

def remove_nikud(text):
    """מסיר ניקוד מטקסט עברי"""
    if not text: return ""
    return re.sub(r'[\u0591-\u05C7]', '', text)

def cleanup_pdf_page(text):
    """ניקוי בסיסי (ישן) - נשמר לתאימות"""
    return text.replace("\xa0", " ").strip()

def advanced_cleanup(text):
    """ניקוי מתקדם של תווים מיוחדים"""
    if not text: return ""
    text = text.replace("\u200f", "").replace("\u200e", "")  # הסרת תווי כיווניות
    text = text.replace("\xa0", " ")
    text = re.sub(r'[\r\n]+', '\n', text)
    return text

# === הפונקציות החדשות שחילצנו מהייבוא הראשי ===

def smart_clean_page_text(page_text):
    """
    מבצע את הניקוי החכם ברמת העמוד:
    - סינון שורות זבל ומספרי עמודים
    - תיקון היפוך פיסוק (RTL)
    - איחוד שורות פיסוק יתומות
    - איחוד פסקאות חכם (Smart Join)
    """
    if not page_text:
        return ""

    # 1. ניקוי שורות זבל
    lines = page_text.split('\n')
    total_lines = len(lines)
    cleaned_lines = []
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) == 0:
            continue
        # סינון מספרי עמודים: מספר בודד שמוקף בשורות ריקות
        if re.match(r'^\s*\d+\s*$', stripped):
            prev_empty = (line_idx == 0) or not lines[line_idx - 1].strip()
            next_empty = (line_idx >= total_lines - 1) or not lines[line_idx + 1].strip()
            if prev_empty or next_empty:
                continue
        if len(stripped) == 1 and not re.match(r'[.!?,;:)(a-zA-Z0-9\u0590-\u05FF]', stripped):
            continue
        cleaned_lines.append(stripped)

    # 2. תיקון סימני פיסוק RTL
    for k in range(len(cleaned_lines)):
        # העברת סימן פיסוק מתחילת השורה לסוף המילה שדבוקה אליו
        cleaned_lines[k] = re.sub(r'^([.!?,;:"\u05F4]+)(\S+)', r'\2\1', cleaned_lines[k])
        # תיקון סדר גרשיים-נקודה
        cleaned_lines[k] = re.sub(r'\.(")', r'\1.', cleaned_lines[k])

    # 3. איחוד שורות פיסוק בודדות לשורה הקודמת
    merged_lines = []
    for line in cleaned_lines:
        if merged_lines and re.match(r'^[.!?,;:)(–\-\]\[]+$', line):
            merged_lines[-1] += line
        else:
            merged_lines.append(line)
    cleaned_lines = merged_lines

    # 4. איחוד פסקאות חכם (Smart Join)
    smart_text = ""
    for j, line in enumerate(cleaned_lines):
        if j > 0:
            prev_line = cleaned_lines[j-1]
            current_starts_with_punct = line and line[0] in '.!?,;:'
            
            if current_starts_with_punct:
                pass
            elif prev_line.endswith(('.', '!', '?', ':', ';', '"')):
                smart_text += "\n"
            else:
                smart_text += " "
        smart_text += line

    return smart_text

def finalize_text_processing(full_text):
    """
    מבצע את הפוליש הסופי על כל הטקסט (Regex Post-Processing)
    """
    # ניקוי כללי
    final_text = advanced_cleanup(full_text)
    
    # תיקונים טיפוגרפיים ספציפיים
    final_text = re.sub(r'\.([^\s\n\d])', r'. \1', final_text)   # רווח אחרי נקודה (לא לפני ספרה - מספרים עשרוניים)
    final_text = re.sub(r',([^\s\n])', r', \1', final_text)   # רווח אחרי פסיק
    final_text = re.sub(r' {2,}', ' ', final_text)            # צמצום רווחים כפולים
    final_text = re.sub(r'\s+([.,!?;:])', r'\1', final_text)  # ביטול רווח לפני פיסוק
    final_text = re.sub(r'\(\s+', '(', final_text)            # ביטול רווח אחרי סוגריים פותחים
    final_text = re.sub(r'\s+\)', ')', final_text)            # ביטול רווח לפני סוגריים סוגרים

    return final_text.strip()