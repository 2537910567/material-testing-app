"""Check conversion status in DB"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from app.database.db_manager import DatabaseManager
db = DatabaseManager()
pid = '6604044a'
files = db.get_files(pid)
for f in files:
    print(f'{f["file_name"]} ({f["file_type"]}): parse={f["parse_status"]} conv={f["conversion_status"]}')
for f in files:
    ct = db.get_setting(f'conversion_type_{f["id"]}')
    cp = db.get_setting(f'converted_png_{f["id"]}')
    if ct or cp:
        print(f'  file#{f["id"]}: conv_type={ct} png={"yes" if cp else "no"}')
db.close()
