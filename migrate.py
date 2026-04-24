import sqlite3

conn = sqlite3.connect("instance/app.db")
cursor = conn.cursor()
cursor.execute("ALTER TABLE consultation ADD COLUMN doctor_id INTEGER;")
conn.commit()
conn.close()
print("Column added successfully")
