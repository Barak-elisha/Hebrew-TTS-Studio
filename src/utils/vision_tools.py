import cv2
# --- העתק את פונקציית החיתוך החכם (מתוך app.py) ---
# אפשר להוסיף אותה לפני המחלקה HebrewTTSStudio

def crop_illustration_only(image_path):
    """
    גרסה v2: חיתוך כירורגי לגרפים ותמונות בלבד (מסנן טקסטים).
    """
    try:
        # 1. טעינה
        img = cv2.imread(image_path)
        if img is None: return False
        
        # המרה לגווני אפור
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 2. הפיכה לבינארי (הפוך: טקסט/קוים בלבן, רקע בשחור)
        # שימוש ב-OTSU לקביעת סף דינאמי וטוב יותר
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # === שלב סינון הטקסט ===
        # יצירת "מסיכה" שתשמש רק לזיהוי המיקום (לא משנה את התמונה המקורית)
        detection_mask = thresh.copy()
        
        # זיהוי שורות טקסט: אלו בד"כ קווים אופקיים
        # אנחנו מחפשים דברים שהם רחבים אבל נמוכים
        contours, _ = cv2.findContours(detection_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        img_h, img_w = img.shape[:2]
        
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            
            # לוגיקה: אם זה נראה כמו שורת טקסט - נצבע את זה בשחור (נמחוק מהזיהוי)
            # תנאי 1: גובה קטן (פחות מ-5% מהדף)
            # תנאי 2: רוחב משמעותי (יותר מ-10% מהדף) - כדי לא למחוק מקרא קטן בתוך גרף
            # תנאי 3: יחס רוחב/גובה קיצוני (טקסט הוא מלבן מאורך)
            
            aspect_ratio = w / float(h)
            is_text_line = (h < img_h * 0.05) and (aspect_ratio > 3)
            
            # מחיקת שורות טקסט מהמסיכה
            if is_text_line:
                cv2.drawContours(detection_mask, [c], -1, (0, 0, 0), -1)

        # === שלב איחוד הגרף ===
        # עכשיו שנשארנו (בתקווה) בלי פסקאות, נאחד את מה שנשאר (קווי הגרף)
        # משתמשים בקרנל קטן יותר (9,9) במקום (25,25) כדי לא לחבר בטעות כותרות קרובות
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        dilated = cv2.dilate(detection_mask, kernel, iterations=4)

        # מציאת קווי המתאר הסופיים
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours: return False

        # מציאת הקונטור הגדול ביותר (הגרף עצמו)
        largest_contour = max(contours, key=cv2.contourArea)
        
        # סינון רעש: אם הגרף קטן מדי (פחות מ-5% משטח הדף), כנראה אין גרף אלא סתם לכלוך
        page_area = img_w * img_h
        if cv2.contourArea(largest_contour) < (page_area * 0.05):
            print(f"Skipping {image_path}: Largest object is too small (likely noise/text remains).")
            return False

        # קבלת המלבן החוסם
        x, y, w, h = cv2.boundingRect(largest_contour)

        # הוספת מעט "אוויר" (Padding), אבל בזהירות לא לצאת מהגבולות
        pad = 15
        x_start = max(0, x - pad)
        y_start = max(0, y - pad)
        x_end = min(img_w, x + w + pad)
        y_end = min(img_h, y + h + pad)

        # ביצוע החיתוך על התמונה המקורית הצבעונית
        cropped_img = img[y_start:y_end, x_start:x_end]
        
        if cropped_img.size == 0: return False

        cv2.imwrite(image_path, cropped_img)
        return True

    except Exception as e:
        print(f"Crop Error: {e}")
        return False