import os
import glob

# directories to skip
skip_dirs = ['.git', '.venv', '.vscode', 'lmlib.egg-info', 'openlmlib.egg-info', '__pycache__', 'build', 'dist', 'node_modules']
skip_exts = ['.pyc', '.whl', '.tar.gz', '.sqlite3', '.db', '.png', '.jpg', '.pack', '.idx']

def replace_in_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return
    
    new_content = content.replace('LMlib', 'OpenLMlib')
    new_content = new_content.replace('lmlib', 'openlmlib')
    new_content = new_content.replace('LMLIB', 'OPENLMLIB')
    
    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, dirs, files in os.walk(r'd:\LMlib'):
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    for file in files:
        if any(file.endswith(ext) for ext in skip_exts):
            continue
        filepath = os.path.join(root, file)
        # Skip this script itself
        if file == 'rename_script.py':
            continue
        replace_in_file(filepath)

# Rename the source directory
src_dir = r'd:\LMlib\lmlib'
dst_dir = r'd:\LMlib\openlmlib'
if os.path.exists(src_dir):
    os.rename(src_dir, dst_dir)
    print(f"Renamed {src_dir} to {dst_dir}")
