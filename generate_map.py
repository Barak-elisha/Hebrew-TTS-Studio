import os

def generate_skeleton(start_path, output_file):
    with open(output_file, 'w', encoding='utf-8') as out:
        out.write("PROJECT ARCHITECTURE SKELETON\n")
        out.write("=============================\n\n")
        
        for root, dirs, files in os.walk(start_path):
            # התעלמות מתיקיות מיותרות
            if '__pycache__' in dirs:
                dirs.remove('__pycache__')
            if '.git' in dirs:
                dirs.remove('.git')
                
            level = root.replace(start_path, '').count(os.sep)
            indent = ' ' * 4 * (level)
            out.write(f'{indent}📂 {os.path.basename(root)}/\n')
            
            subindent = ' ' * 4 * (level + 1)
            
            for f in files:
                if f.endswith('.py'):
                    file_path = os.path.join(root, f)
                    out.write(f'{subindent}🐍 {f}\n')
                    
                    # קריאת הקובץ וחיפוש הגדרות
                    try:
                        with open(file_path, 'r', encoding='utf-8') as py_file:
                            lines = py_file.readlines()
                            for line in lines:
                                stripped = line.strip()
                                # שליפת מחלקות ופונקציות בלבד
                                if stripped.startswith("class ") or stripped.startswith("def "):
                                    # שמירה על האינדנטציה המקורית כדי להבין היררכיה
                                    clean_line = line.rstrip().split(':')[0]
                                    out.write(f'{subindent}    {clean_line}\n')
                    except Exception as e:
                        out.write(f'{subindent}    [Error reading file]\n')

if __name__ == "__main__":
    # סורק את התיקייה הנוכחית
    current_dir = os.getcwd()
    output = "project_context.txt"
    
    print(f"Generating skeleton for: {current_dir}")
    generate_skeleton(current_dir, output)
    print(f"Done! File created: {output}")