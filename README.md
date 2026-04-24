
# RBAC Health (Flask + SQLite)

## Setup
```bash
python -m venv venv
source venv/bin/activate  # on Windows: venv\Scripts\activate
pip install flask flask_sqlalchemy werkzeug
python app.py
```
Then open http://127.0.0.1:5000

## Roles & Demo Logins
- Admin: admin / admin123
- Doctor: doc / doc123
- Lab: lab / lab123
- IT Exec: it / it123

## Features
- Admin: user mgmt (create/remove), pharmacy add/remove (no patient data access).
- Doctor: patient registration; consultation (fetch by UHID via `/api/patient/<uhid>`, vitals); dynamic lab test requests; Save & Next → Prescription; dynamic drugs, print & download.
- Lab: dashboard shows pending tests; file upload for reports; once all tests have at least 1 report, request becomes Completed; reports downloadable by Doctor.
- IT Exec: simple analytics (counts).

## Color Palette
- Background: #F3F4F6
- Headings:   #2d5a2f
- Icons:      #3a86d7

## Notes
- Uploads are saved in `uploads/`. Only Doctors can download reports.
- Change `SECRET_KEY` in `app.py` for production.
