# src/utils/settings_manager.py
import json
import os
from datetime import datetime

class SettingsManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.settings = {}

    def load(self, default_settings):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return default_settings.copy()

    def save_to_disk(self, settings_dict):
        """הפעולה הפיזית של הכתיבה לדיסק"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(settings_dict, f, indent=4, ensure_ascii=False)
            return True, datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            return False, str(e)
        
    def load_settings(self, default_settings):
        """
        טעינה בטוחה: אם הקובץ קיים ותקין - מחזירה את תוכנו.
        בכל מקרה אחר - מחזירה עותק של הגדרות ברירת המחדל.
        """
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # וידוא שקיבלנו דיקשנרי ולא משהו אחר
                    if isinstance(data, dict):
                        print(f"[DEBUG] Settings loaded successfully from {self.config_file}")
                        return data
            except Exception as e:
                print(f"[ERROR LOAD] Could not parse config file: {e}")
        
        print("[DEBUG] Using default settings (config file missing or corrupt)")
        return default_settings.copy()