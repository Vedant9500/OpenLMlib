import sys, re

path = 'd:/LMlib/openlmlib/collab/collab_mcp.py'
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Replace the connection code
text = re.sub(
    r'( +)conn, +sessions_dir += +_get_collab_connection\(\)\n\1try:\n',
    r'\1with _collab_connection() as (conn, sessions_dir):\n',
    text
)

text = re.sub(
    r'( +)conn, +_ += +_get_collab_connection\(\)\n\1try:\n',
    r'\1with _collab_connection() as (conn, _):\n',
    text
)

# Remove finally blocks
text = re.sub(
    r'( +)finally:\n\1    conn\.close\(\)\n',
    r'',
    text
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
    
print("Refactored collab_mcp.py!")
