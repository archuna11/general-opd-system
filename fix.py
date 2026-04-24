import sqlite3

conn = sqlite3.connect("instance/app.db")
cur = conn.cursor()

# Add ai_diagnosis column
try:
    cur.execute("ALTER TABLE consultation ADD COLUMN ai_diagnosis TEXT")
except Exception as e:
    print("ai_diagnosis:", e)

# Add final_doctor_diagnosis column
try:
    cur.execute("ALTER TABLE consultation ADD COLUMN final_doctor_diagnosis TEXT")
except Exception as e:
    print("final_doctor_diagnosis:", e)

conn.commit()
conn.close()

print("Migration completed")
