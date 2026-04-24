from flask import Flask, render_template, render_template_string, redirect, url_for, Response, request, session, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
from datetime import datetime
import sqlite3
from sqlalchemy import func
from datetime import datetime
from collections import Counter
import io
import base64
import matplotlib
matplotlib.use('Agg')  # Use a non-GUI backend for Flask
import matplotlib.pyplot as plt
from flask import render_template
import pytz
import requests
import time
import json
import threading
import uuid
from werkzeug.exceptions import BadRequest

from radiology_bp import radiology_bp


# admin/admin123 doc/doc123 lab/lab123 it/it123 -- usernames and passwords


DB_FILE = "database.db"



app = Flask(__name__, instance_relative_config=True)
app.config['SECRET_KEY'] = 'change_this_secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
os.makedirs(app.instance_path, exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs("downloads", exist_ok=True) # Ensure downloads directory exists

db = SQLAlchemy(app)




# New: everything under /radiology
app.register_blueprint(radiology_bp, url_prefix="/radiology")





# ----------------- MODELS -----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # Admin, Doctor, Lab, IT Exec

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uhid = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(200))

    # ✅ New fields
    marital_status = db.Column(db.String(20))
    occupation = db.Column(db.String(120))
    created_at = db.Column(db.DateTime)

  
    # latest vitals for convenience
    vit_bp = db.Column(db.String(20))
    vit_temp = db.Column(db.Float)
    vit_spo2 = db.Column(db.Integer)
    vit_pulse = db.Column(db.Integer)
    vit_rr = db.Column(db.Integer)

class Consultation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Vitals
    v_bp = db.Column(db.String(20))
    v_temp = db.Column(db.Float)
    v_spo2 = db.Column(db.Integer)
    v_pulse = db.Column(db.Integer)
    v_rr = db.Column(db.Integer)

    # Complaints & History
    cc = db.Column(db.Text)
    pmh = db.Column(db.Text)
    pmxh = db.Column(db.Text)
    surgical = db.Column(db.Text)
    family = db.Column(db.Text)
    allergy = db.Column(db.Text)
    obgyn = db.Column(db.Text)
    social = db.Column(db.Text)

    # Systemic Examination
    cardio = db.Column(db.Text)
    resp = db.Column(db.Text)
    abdomen = db.Column(db.Text)
    cns = db.Column(db.Text)
    msk = db.Column(db.Text)

    # Provisional Diagnosis
    provisional_dx = db.Column(db.Text)
    ai_diagnosis = db.Column(db.Text)
    final_doctor_diagnosis = db.Column(db.Text)


    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())


class LabRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    tests = db.Column(db.String(500), nullable=False) # Stored as a JSON string
    results = db.Column(db.String(500), nullable=True) # Stored as a JSON string
    priority = db.Column(db.String(20), nullable=True)
    specimen = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



class Prescription(db.Model):
    id = db.Column(db.Integer, primary_key=True) 
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False) 

    # Existing fields
    complaints = db.Column(db.Text) 
    pmh = db.Column(db.Text)
    pmxh = db.Column(db.Text)
    diagnosis = db.Column(db.Text) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Store all drugs as one formatted text
    drugs = db.Column(db.Text)

    # New fields
    advice = db.Column(db.Text)
    follow_up = db.Column(db.Date)

 
 


class Drug(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey('prescription.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    dose = db.Column(db.String(40))
    unit = db.Column(db.String(20))
    frequency = db.Column(db.String(20))
    duration = db.Column(db.String(20))
    duration_unit = db.Column(db.String(30))
    when_to_take = db.Column(db.String(30))





# ----------------- RBAC helpers -----------------
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrap

def require_roles(*roles):
    def decorator(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            user = current_user()
            if not user or user.role.lower() not in [r.lower() for r in roles]:
                flash("Access denied", "error")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrap
    return decorator


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.session.get(User, uid)  # Updated to SQLAlchemy 2.0 syntax


# ----------------- Setup default users -----------------
# remove the @app.before_first_request decorator
def setup_defaults():
    db.create_all()
    if User.query.count() == 0:
        users = [
            User(username="admin", password=generate_password_hash("admin123"), role="Admin"),
            User(username="doc", password=generate_password_hash("doc123"), role="Doctor"),
            User(username="lab", password=generate_password_hash("lab123"), role="Lab"),
            User(username="it", password=generate_password_hash("it123"), role="IT Exec"),
        ]
        db.session.add_all(users)
        db.session.commit()

# call it once when the app starts
with app.app_context():
    db.create_all()
    setup_defaults()

# ----------------- Routes -----------------
@app.route('/')
def index():
    user = current_user()
    if user:
        if user.role == "Admin":
            return redirect(url_for('admin'))
        if user.role == "Doctor":
            return redirect(url_for('patient_registration'))
        if user.role == "Lab":
            return redirect(url_for('lab_dashboard'))
        if user.role == "IT Exec":
            return redirect(url_for('it_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        flash("Invalid credentials", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))



@app.route("/doctor/dashboard")
def doctor_dashboard():
    return render_template("doctor_dashboard.html")



# ---------- Admin: User Management + Pharmacy (no patient data) ----------
@app.route('/admin', methods=['GET','POST'])
@login_required
@require_roles('Admin')
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_user':
            username = request.form.get('um_user','').strip()
            password = request.form.get('um_pass','').strip()
            role = request.form.get('um_role','')
            if not username or not password or not role:
                flash("All fields required", "error")
            elif User.query.filter_by(username=username).first():
                flash("Username already exists", "error")
            else:
                db.session.add(User(username=username, password=generate_password_hash(password), role=role))
                db.session.commit()
                flash("User added", "success")
        elif action == 'del_user':
            uid = request.form.get('user_id')
            me = current_user()
            if str(me.id) == str(uid):
                flash("You cannot delete yourself", "error")
            else:
                u = User.query.get(uid)
                if u:
                    db.session.delete(u)
                    db.session.commit()
                    flash("User removed", "success")
        
    return render_template('admin.html', users=User.query.all())




# ---------- Doctor: Patient Registration ----------
from datetime import datetime

@app.route('/patient_registration', methods=['GET','POST'])
@login_required
@require_roles('Doctor')
def patient_registration():
    # Generate next UHID
    last_patient = Patient.query.order_by(Patient.id.desc()).first()
    if last_patient and last_patient.uhid.startswith("UHID"):
        last_num = int(last_patient.uhid.replace("UHID", ""))
        new_uhid = f"UHID{last_num+1:03d}"
    else:
        new_uhid = "UHID001"

    # Current IST time
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist).strftime("%d-%m-%Y %H:%M:%S")

    if request.method == 'POST':
        uhid = request.form.get('uhid','').strip()
        name = request.form.get('name','').strip()
        if not uhid or not name:
            flash("UHID and Name are required", "error")
        else:
            p = Patient.query.filter_by(uhid=uhid).first()
            if not p:
                p = Patient(uhid=uhid, name=name)

            # Update fields
            p.age = request.form.get('age') or None
            p.gender = request.form.get('gender') or None
            p.email = request.form.get('email') or None
            p.phone = request.form.get('phone') or None
            p.address = request.form.get('address') or None
            p.marital_status = request.form.get('marital_status') or None
            p.occupation = request.form.get('occupation') or None
            p.created_at = datetime.now(ist)   # save actual datetime object

            db.session.add(p)
            db.session.commit()
            flash("Patient registration successful", "success")

            # Redirect to consultation page after registration
            return redirect(url_for('consultation'))

    return render_template('patient_registration.html',
                           new_uhid=new_uhid,
                           now=now)


# AJAX: fetch patient by UHID
@app.route('/api/patient/<uhid>')
@login_required
@require_roles('Doctor')
def api_patient(uhid):
    p = Patient.query.filter_by(uhid=uhid).first()
    if not p:
        return jsonify({"ok": False}), 404
    return jsonify({
        "ok": True,
        "patient": {
            "uhid": p.uhid, "name": p.name, "age": p.age, "gender": p.gender,
            "email": p.email, "phone": p.phone, "address": p.address,
            "vitals": {"bp": p.vit_bp, "temp": p.vit_temp, "spo2": p.vit_spo2, "pulse": p.vit_pulse, "rr": p.vit_rr}
        }
    })


#----------- Doctor: Prescription ----------
@app.route('/prescription', methods=['GET', 'POST'])
@login_required
@require_roles('Doctor')
def prescription():
    uhid = request.args.get('uhid', '').strip()
    patient = Patient.query.filter_by(uhid=uhid).first() if uhid else None

    if request.method == 'POST':
        action = request.form.get('action')  # which button was clicked
        uhid_post = request.form.get('rx_uhid', '').strip()
        patient = Patient.query.filter_by(uhid=uhid_post).first()
        if not patient:
            flash("Patient not found", "error")
            return redirect(url_for('prescription', uhid=uhid_post))

        # Get latest consultation for patient, or create one
        cons = Consultation.query.filter_by(patient_id=patient.id)\
                                 .order_by(Consultation.id.desc())\
                                 .first()
        if not cons:
            cons = Consultation(patient_id=patient.id, doctor_id=current_user().id)
            db.session.add(cons)
            db.session.commit()

        # Convert follow-up date string to datetime.date
        follow_up_str = request.form.get("follow_up")
        follow_up_date = datetime.strptime(follow_up_str, "%Y-%m-%d").date() if follow_up_str else None

        # Save prescription with additional fields
        new_prescription = Prescription(
            consultation_id=cons.id,
            patient_id=patient.id,
            complaints=request.form.get("rx_cc"),
            pmh=request.form.get("rx_pmh"),
            pmxh=request.form.get("rx_pmxh"),
            diagnosis=request.form.get("rx_dx"),
            drugs=request.form.get("drugs"),
            advice=request.form.get("advice"),
            follow_up=follow_up_date
        )
        db.session.add(new_prescription)
        db.session.commit()

        flash("Prescription saved", "success")

        # Redirect to summary page showing consultation + prescription
        if action == 'next':
            return redirect(url_for('patient_prescription', uhid=patient.uhid))

        return redirect(url_for('prescription', uhid=patient.uhid))

    # Show saved prescriptions
    saved_prescriptions = []
    if patient:
        saved_prescriptions = Prescription.query.filter_by(patient_id=patient.id)\
                                                .order_by(Prescription.created_at.desc())\
                                                .all()

    return render_template(
        'prescription.html',
        patient=patient,
        saved=saved_prescriptions
    )



# ---------- Patient Prescription Page ----------
@app.route('/patient_prescription/<uhid>')
@login_required
@require_roles('Doctor')
def patient_prescription(uhid):
    # Fetch patient
    patient = Patient.query.filter_by(uhid=uhid).first_or_404()

    # Get latest consultation (can be None)
    consultation = Consultation.query.filter_by(patient_id=patient.id)\
                                     .order_by(Consultation.created_at.desc())\
                                     .first()

    # Get latest prescription
    prescription = Prescription.query.filter_by(patient_id=patient.id)\
                                     .order_by(Prescription.created_at.desc())\
                                     .first_or_404()

    return render_template(
        "patient_prescription.html",
        patient=patient,
        consultation=consultation,
        prescription=prescription
    )


@app.route('/consultation', methods=['GET','POST'])
@login_required
@require_roles('Doctor')
def consultation():
    if request.method == 'POST':
        uhid = request.form.get('c_uhid_hidden', '').strip()
        patient = Patient.query.filter_by(uhid=uhid).first()
        if not patient:
            flash("Patient not found", "error")
            return redirect(url_for('consultation_index'))

        # create a new consultation record
        cons = Consultation(
            patient_id=patient.id,
            doctor_id=current_user().id,
            created_at=datetime.utcnow(),
            v_bp=request.form.get('v_bp'),
            v_temp=request.form.get('v_temp'),
            v_spo2=request.form.get('v_spo2'),
            v_pulse=request.form.get('v_pulse'),
            v_rr=request.form.get('v_rr'),
            cc=request.form.get('cc'),
            pmh=request.form.get('pmh'),
            pmxh=request.form.get('pmxh'),
            surgical=request.form.get('surgical'),
            family=request.form.get('family'),
            allergy=request.form.get('allergy'),
            obgyn=request.form.get('obgyn'),
            social=request.form.get('social'),
            cardio=request.form.get('cardio'),
            resp=request.form.get('resp'),
            abdomen=request.form.get('abdomen'),
            cns=request.form.get('cns'),
            msk=request.form.get('msk'),
            provisional_dx=request.form.get('provisional_dx')
             )
        db.session.add(cons)
        db.session.commit()

        flash("Consultation saved", "success")
        return redirect(url_for('prescription', uhid=uhid))

    return render_template('consultation.html')


@app.route("/consultation/<uhid>", methods=["GET", "POST"])
@login_required
@require_roles("Doctor")
def consultation_detail(uhid):
    patient = Patient.query.filter_by(uhid=uhid).first()
    last_consultation = None
    last_prescription = None
    if patient:
        last_consultation = Consultation.query.filter_by(patient_id=patient.id)\
                                              .order_by(Consultation.created_at.desc())\
                                              .first()
        if last_consultation:
            last_prescription = Prescription.query.filter_by(consultation_id=last_consultation.id).first()

    return render_template(
        "consultation.html",
        patient=patient,
        last_consultation=last_consultation,
        last_prescription=last_prescription
    )


@app.route("/api/consultations/all/<uhid>")
def get_all_consultations(uhid):
    patient = Patient.query.filter_by(uhid=uhid).first()
    if not patient:
        return jsonify([])
    cons_list = Consultation.query.filter_by(patient_id=patient.id)\
                  .order_by(Consultation.created_at.desc()).all()
    result = []
    for cons in cons_list:
        rx = Prescription.query.filter_by(consultation_id=cons.id).first()
        result.append({
            "created_at": cons.created_at.strftime("%d-%m-%Y %H:%M"),
            "cc": cons.cc,
            "pmh": cons.pmh,
            "pmxh": cons.pmxh,
            "allergy": cons.allergy,
            "provisional_dx": cons.provisional_dx,
            "drugs": rx.drugs if rx else ""
        })
    return jsonify(result)

@app.route("/ai/diagnosis_only", methods=["POST"])
@login_required
@require_roles("Doctor")
def ai_diagnosis_only():
    data = request.json

    clinical_context = f"""
Chief Complaints: {data.get('cc')}
Past Medical History: {data.get('pmh')}
Vitals:
Temperature: {data.get('temp')}
SpO2: {data.get('spo2')}
Pulse: {data.get('pulse')}
"""

    prompt = f"""
You are a senior physician.

Based on the clinical context below, output ONLY the most likely diagnosis.

Rules:
- Output ONLY the diagnosis name
- No explanation
- No formatting

Clinical Context:
{clinical_context}

Final Diagnosis:
"""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "medllama2",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1}
        },
        timeout=60
    )

    diagnosis = response.json().get("response", "").strip()

    # 🔥 SAVE AI DIAGNOSIS INTO CONSULTATION
    uhid = data.get("uhid")
    if uhid:
        patient = Patient.query.filter_by(uhid=uhid).first()
        if patient:
            cons = Consultation.query.filter_by(patient_id=patient.id)\
                                     .order_by(Consultation.created_at.desc())\
                                     .first()
            if cons:
                cons.provisional_dx = diagnosis      # 🤖 provisional
                cons.ai_diagnosis = diagnosis
                db.session.commit()

    return jsonify({"diagnosis": diagnosis})


# ---------- Download Prescription ----------
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io
from flask import send_file

@app.route('/download_prescription/<int:prescription_id>')
@login_required
@require_roles('Doctor')
def download_prescription(prescription_id):
    # Fetch prescription
    rx = Prescription.query.get_or_404(prescription_id)
    patient = Patient.query.get(rx.patient_id)
    consultation = Consultation.query.filter_by(patient_id=patient.id)\
                                     .order_by(Consultation.created_at.desc())\
                                     .first()

    # Create PDF in memory
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4

    y = height - 50  # start position from top

    def write_line(text, offset=18):
        nonlocal y
        c.drawString(50, y, text)
        y -= offset

    write_line(f"Patient: {patient.name} (UHID: {patient.uhid})", 22)
    write_line(f"Age: {patient.age}, Gender: {patient.gender}", 22)
    write_line("--- Vitals ---", 20)
    write_line(f"Blood Pressure: {consultation.v_bp or ''}")
    write_line(f"Temperature: {consultation.v_temp or ''}")
    write_line(f"SPO2: {consultation.v_spo2 or ''}")
    write_line(f"Pulse Rate: {consultation.v_pulse or ''}")
    write_line(f"Respiratory Rate: {consultation.v_rr or ''}", 20)

    write_line("--- Chief Complaints ---", 20)
    write_line(consultation.cc or '', 20)

    write_line("--- Past History ---", 20)
    write_line(f"Past Medical History: {consultation.pmh or ''}")
    write_line(f"Past Medication History: {consultation.pmxh or ''}")
    write_line(f"Surgical History: {consultation.surgical or ''}")
    write_line(f"Family History: {consultation.family or ''}")
    write_line(f"Allergy: {consultation.allergy or ''}")
    write_line(f"Obstetric/Gynecological History: {consultation.obgyn or ''}")
    write_line(f"Social History: {consultation.social or ''}", 20)

    write_line("--- Systemic Examination ---", 20)
    write_line(f"Cardiovascular: {consultation.cardio or ''}")
    write_line(f"Respiratory: {consultation.resp or ''}")
    write_line(f"Abdomen: {consultation.abdomen or ''}")
    write_line(f"CNS: {consultation.cns or ''}")
    write_line(f"Musculoskeletal: {consultation.msk or ''}", 20)

    write_line("--- Provisional Diagnosis ---", 20)
    write_line(consultation.provisional_dx or '', 20)

    write_line("--- Prescription ---", 20)
    write_line(f"Drugs:\n{rx.drugs or ''}", 20)
    write_line(f"Advice / Lifestyle:\n{rx.advice or ''}", 20)
    write_line(f"Follow-up Date: {rx.follow_up if rx.follow_up else ''}", 20)

    c.showPage()
    c.save()
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"{patient.uhid}.pdf",  # PDF named as UHID
        mimetype='application/pdf'
    )



# --- Doctor : Lab Integration ---

TEST_CATEGORIES = {
    'biochemistry': {
        'Kidney Function': ['GLU', 'UREA', 'CREATININE'],
        'Liver Function': ['SGOT', 'SGPT', 'ALBUMIN', 'TOTAL_BILIRUBIN'],
        'Thyroid Function': ['TSH', 'T3', 'T4'],
        'Cardiac Markers': ['TROPONIN_I'],
        'Lipid Profile': ['TOTAL_CHOLESTEROL', 'HDL', 'LDL'],
        'Electrolytes': ['SODIUM', 'POTASSIUM']
    },
    'microbiology': {
        'Wet Mount & Staining': ['GRAM_STAIN', 'HANGING_DROP', 'INDIA_INK', 'STOOL_OVA', 'KOH_MOUNT', 'ZN_STAIN'],
        'Culture & Sensitivity': ['BLOOD_CULTURE', 'URINE_CULTURE', 'SPUTUM_CULTURE', 'WOUND_CULTURE', 'THROAT_CULTURE', 'CSF_CULTURE'],
        'Fungal Culture': ['FUNGAL_CULTURE', 'FUNGAL_ID', 'ANTIFUNGAL_SENS'],
        'Serology': ['WIDAL', 'TYPHIDOT', 'DENGUE_NS1', 'MALARIA_AG', 'HIV_ELISA', 'HBSAG']
    },
    'pathology': {
        'Histopathology': ['BIOPSY_HISTOPATHOLOGY', 'SURGICAL_PATHOLOGY'],
        'Hematology': ['CBC', 'PERIPHERAL_SMEAR', 'BONE_MARROW', 'COAGULATION'],
        'Immunohistochemistry': ['IHC_MARKERS', 'SPECIAL_STAINS', 'MOLECULAR_PATH']
    }
}

@app.route("/lab", methods=["GET", "POST"])
@login_required
@require_roles('Doctor')
def lab_request_page():
    """Renders the lab test request form or processes a new request."""
    user = current_user()
    patient = Patient.query.first() # Placeholder - replace with actual patient lookup
    if not patient:
      flash("No patients found in the database. Cannot create a lab request.", 'warning')
      return redirect(url_for('home'))

    if request.method == "POST":
        patient_uhid = request.form.get("patient_uhid")
        priority = request.form.get("priority")
        specimen = request.form.get("specimen")
        selected_tests = request.form.getlist("tests")
        
        patient = Patient.query.filter_by(uhid=patient_uhid).first()
        if not patient:
            flash("Invalid Patient UHID.", 'danger')
            return redirect(url_for('lab_request_page'))

        new_request = LabRequest(
            patient_id=patient.id,
            priority=priority,
            specimen=specimen,
            tests=json.dumps(selected_tests),
            status='Pending'
        )
        db.session.add(new_request)
        db.session.commit()
        
        flash(f"Lab test request for Patient {patient_uhid} submitted successfully with Order ID: {new_request.id}", 'success')
        return redirect(url_for('lab_history_page'))

    return render_template('lab_request.html', 
                           test_categories=TEST_CATEGORIES, 
                           user=user)

@app.route("/lab/history")
@login_required
@require_roles('Doctor')
def lab_history_page():
    """Displays the history of submitted lab requests."""
    # This fetches all lab requests. You may want to filter them based on the logged-in user or department.
    lab_requests = LabRequest.query.order_by(LabRequest.created_at.desc()).all()
    
    # We'll need patient UHID for display, so we'll fetch them as well
    patients = Patient.query.all()
    patient_map = {p.id: p.uhid for p in patients}

    # Update statuses if needed (you could add a background task to do this)
    # For now, we'll assume the status is updated by a separate process.

    return render_template('lab_history.html', 
                           lab_requests=lab_requests,
                           patient_map=patient_map)

@app.route("/lab/results/<int:order_id>")
@login_required
@require_roles('Doctor')
def lab_view_results(order_id):
    """Fetches and displays the detailed results for a specific order."""
    lab_request = LabRequest.query.get_or_404(order_id)
    patient = Patient.query.get(lab_request.patient_id)
    
    tests = json.loads(lab_request.tests)
    results = json.loads(lab_request.results) if lab_request.results else {}

    return render_template('lab_results.html', 
                           lab_request=lab_request,
                           patient=patient,
                           tests=tests,
                           results=results)

@app.route("/lab/download/<int:order_id>")
@login_required
@require_roles('Doctor')
def lab_serve_report(order_id):
    """Generates and serves a lab report as a text file."""
    lab_request = LabRequest.query.get_or_404(order_id)
    patient = Patient.query.get(lab_request.patient_id)
    
    report_data = f"Lab Report for Order ID: {lab_request.id}\n"
    report_data += f"Patient UHID: {patient.uhid}\n"
    report_data += f"Status: {lab_request.status}\n"
    report_data += f"Tests Requested: {', '.join(json.loads(lab_request.tests))}\n\n"
    report_data += "--- Results ---\n"
    if lab_request.results:
        results = json.loads(lab_request.results)
        for test, result in results.items():
            report_data += f"{test}: {result}\n"
    else:
        report_data += "Results not yet available.\n"
    
    filename = f"lab_report_{order_id}.txt"
    filepath = os.path.join(app.root_path, "downloads", filename)
    with open(filepath, 'w') as f:
        f.write(report_data)
        
    return send_from_directory(os.path.join(app.root_path, "downloads"), filename, as_attachment=True)


@app.route('/home')
@login_required
@require_roles('Doctor')
def home():
    return redirect(url_for('lab_history_page'))  # or doctor_dashboard, etc.




# ---------- Radiology API Simulators ----------


# In-memory "database" to simulate scan availability
SCAN_DATABASE = {}
REQUEST_QUEUE = {}
dicom_id_counter = 0
request_id_counter = 0

def get_next_dicom_id():
    global dicom_id_counter
    dicom_id_counter += 1
    return f"DICOM-{dicom_id_counter}"

def get_next_request_id():
    global request_id_counter
    request_id_counter += 1
    return f"REQ-{request_id_counter}"

@app.route('/api/v1/get_or_request_scan', methods=['POST'])
def get_or_request_scan():
    """Simulates the radiology server API to either get an existing scan or queue a new one."""
    try:
        data = request.json
        uhid = data['uhid']
        scan_type = data['type_of_scan']
        body_part = data['body_part']
    except (BadRequest, KeyError) as e:
        return jsonify({"error": f"Invalid request: {e}"}), 400

    # 1. Check if a matching scan already exists
    if uhid in SCAN_DATABASE:
        scan = SCAN_DATABASE[uhid]
        mock_dicom_data = b'Mock DICOM data for ' + uhid.encode('utf-8')
        response = Response(mock_dicom_data, mimetype='application/dicom')
        response.headers['Content-Disposition'] = f'attachment; filename={scan["scan_id"]}.dcm'
        return response, 200

    # 2. If no scan exists, create a new request and return a 202
    request_id = get_next_request_id()
    new_request = {
        "id": request_id,
        "uhid": uhid,
        "scan_type": scan_type,
        "body_part": body_part,
        "status": "Pending",
        "scan_id": get_next_dicom_id()
    }
    REQUEST_QUEUE[request_id] = new_request

    return jsonify({"request_id": request_id, "status": "Request accepted, pending completion"}), 202





#---------- Doctor: Analytics Dashboard ----------

# import matplotlib
# matplotlib.use('Agg')
# import matplotlib.pyplot as plt
# import io
# import base64

# def fig_to_base64(fig):
#     buf = io.BytesIO()
#     fig.savefig(buf, format="png", bbox_inches="tight")
#     buf.seek(0)
#     return base64.b64encode(buf.getvalue()).decode("utf-8")

# @app.route("/analytics_dashboard")
# @login_required
# @require_roles("Doctor")
# def analytics_dashboard():
#     total_patients = Patient.query.count()
#     total_males = Patient.query.filter_by(gender="Male").count()
#     total_females = Patient.query.filter_by(gender="Female").count()

#     age_groups = {"0-18": 0, "19-35": 0, "36-50": 0, "51+": 0}
#     for p in Patient.query.all():
#         try:
#             if p.age is None:
#                 continue
#             age = int(p.age)
#             if age <= 18:
#                 age_groups["0-18"] += 1
#             elif age <= 35:
#                 age_groups["19-35"] += 1
#             elif age <= 50:
#                 age_groups["36-50"] += 1
#             else:
#                 age_groups["51+"] += 1
#         except Exception as e:
#             print("Error parsing age:", e)
#             continue

#     # Age chart
#     fig, ax = plt.subplots()
#     ax.bar(age_groups.keys(), age_groups.values(), color="#3a86d7")
#     ax.set_title("Age Distribution", color="#2d5a2f")
#     ax.set_ylabel("Number of Patients", color="#2d5a2f")
#     age_chart = fig_to_base64(fig)
#     plt.close(fig)

#     # Gender chart
#     fig, ax = plt.subplots()
#     if total_males + total_females > 0:
#         ax.pie(
#             [total_males, total_females],
#             labels=["Male", "Female"],
#             colors=["#3a86d7", "#ff6384"],
#             autopct="%1.1f%%"
#         )
#     else:
#         ax.text(0.5, 0.5, "No Data", ha="center", va="center", color="#2d5a2f")
#     ax.set_title("Gender Ratio", color="#2d5a2f")
#     gender_chart = fig_to_base64(fig)
#     plt.close(fig)

#     return render_template(
#         "analytics_dashboard.html",
#         total_patients=total_patients,
#         total_males=total_males,
#         total_females=total_females,
#         age_chart=age_chart,
#         gender_chart=gender_chart
    # )@app.route("/analytics_dashboard")


# ---------- Doctor: Analytics Dashboard ----------
@app.route('/analytics_dashboard')
@login_required
@require_roles('Doctor')
def analytics_dashboard():
    import io, base64
    from collections import Counter
    import matplotlib.pyplot as plt

    # Helper to convert matplotlib figs to base64
    def fig_to_base64(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    # ---------------- Summary Stats ----------------
    total_patients = Patient.query.count()
    total_males = Patient.query.filter_by(gender="Male").count()
    total_females = Patient.query.filter_by(gender="Female").count()

    # Collect all prescriptions (just drug names)
    all_drugs = []
    for p in Prescription.query.all():
        if p.drugs:
            for line in p.drugs.split("\n"):
                drug_name = line.strip().split()[0] if line.strip() else None
                if drug_name:
                    all_drugs.append(drug_name)

    # Common drug
    most_common_drug = Counter(all_drugs).most_common(1)[0][0] if all_drugs else "N/A"

    # Abnormal temperatures
    abnormal_consults = Consultation.query.filter(
        (Consultation.v_temp != None) &
        ((Consultation.v_temp > 100.4) | (Consultation.v_temp < 95))
    ).all()
    abnormal_temps = [c.v_temp for c in abnormal_consults]

    # Abnormal SpO2
    abnormal_spo2 = Consultation.query.filter(
        (Consultation.v_spo2 != None) & (Consultation.v_spo2 < 95)
    ).all()
    spo2_values = [c.v_spo2 for c in abnormal_spo2]

    # ---------------- Charts ----------------
    # Age Distribution
    age_groups = {"0-18":0, "19-35":0, "36-50":0, "51+":0}
    for p in Patient.query.all():
        try:
            if p.age is None: continue
            age = int(p.age)
            if age <= 18: age_groups["0-18"] += 1
            elif age <= 35: age_groups["19-35"] += 1
            elif age <= 50: age_groups["36-50"] += 1
            else: age_groups["51+"] += 1
        except:
            continue

    fig, ax = plt.subplots(facecolor="#F3F4F6")
    ax.bar(age_groups.keys(), age_groups.values(), color="#3a86d7")
    ax.set_title("Age Distribution", color="#2d5a2f")
    age_chart = fig_to_base64(fig)
    plt.close(fig)

    # Gender Ratio
    fig, ax = plt.subplots(facecolor="#F3F4F6")
    if total_males + total_females > 0:
        ax.pie([total_males, total_females],
               labels=["Male", "Female"],
               colors=["#3a86d7", "#ff6384"],
               autopct="%1.1f%%")
    else:
        ax.text(0.5, 0.5, "No Data", ha="center", va="center")
    ax.set_title("Gender Ratio", color="#2d5a2f")
    gender_chart = fig_to_base64(fig)
    plt.close(fig)

    # Prescribed Drugs (Pie)
    top_drugs = Counter(all_drugs).most_common(5)
    labels, values = zip(*top_drugs) if top_drugs else ([], [])
    fig, ax = plt.subplots(facecolor="#F3F4F6")
    if labels:
        ax.pie(values, labels=labels, autopct="%1.1f%%",
               colors=plt.cm.tab20.colors)
    else:
        ax.text(0.5, 0.5, "No Data", ha="center", va="center")
    ax.set_title("Top Prescribed Drugs", color="#2d5a2f")
    drug_chart = fig_to_base64(fig)
    plt.close(fig)

    # Abnormal Temperature
    fig, ax = plt.subplots(facecolor="#F3F4F6")
    if abnormal_temps:
        ax.hist(abnormal_temps, bins=10, color="#ff6384", edgecolor="#b91c1c")
    else:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center')
    ax.set_title("Abnormal Temperature (°F)", color="#2d5a2f")
    temperature_chart = fig_to_base64(fig)
    plt.close(fig)

    # Abnormal SpO2 (Histogram)
    fig, ax = plt.subplots(facecolor="#F3F4F6")
    if spo2_values:
        ax.hist(spo2_values, bins=10, color="#3a86d7", edgecolor="#1d4ed8")
        ax.set_xlabel("SpO₂ (%)")
        ax.set_ylabel("Count")
    else:
        ax.text(0.5, 0.5, "No Data", ha="center", va='center')
    ax.set_title("Abnormal SpO₂ Distribution", color="#2d5a2f")
    spo2_chart = fig_to_base64(fig)
    plt.close(fig)

    return render_template(
        "analytics_dashboard.html",
        total_patients=total_patients,
        total_males=total_males,
        total_females=total_females,
        most_common_drug=most_common_drug,
        age_chart=age_chart,
        gender_chart=gender_chart,
        drug_chart=drug_chart,
        temperature_chart=temperature_chart,
        spo2_chart=spo2_chart
    )



# ---------- Doctor: View Patient Records ----------

# @app.route("/view_records", methods=["GET", "POST"])
# @login_required
# @require_roles("Doctor")
# def view_records():
#     search_query = request.args.get("q", "").strip()

#     query = Patient.query
#     if search_query:
#         query = query.filter(
#             (Patient.uhid.ilike(f"%{search_query}%")) |
#             (Patient.name.ilike(f"%{search_query}%"))
#         )

#     patients = query.all()
#     records = []

#     for patient in patients:
#         # Get latest consultation
#         consultation = Consultation.query.filter_by(patient_id=patient.id)\
#                                          .order_by(Consultation.created_at.desc())\
#                                          .first()
#         # Get latest prescription
#         prescription = Prescription.query.filter_by(patient_id=patient.id)\
#                                          .order_by(Prescription.created_at.desc())\
#                                          .first()

#         if consultation or prescription:
#             # Format BP as "systolic/diastolic" if available
#             bp_value = ""
#             if consultation and getattr(consultation, "v_bp_systolic", None) and getattr(consultation, "v_bp_diastolic", None):
#                 bp_value = f"{consultation.v_bp_systolic}/{consultation.v_bp_diastolic}"

#             # Format drugs to preserve line breaks
#             drugs_display = ""
#             if prescription and prescription.drugs:
#                 drugs_display = "\n".join([line.strip() for line in prescription.drugs.split("\n") if line.strip()])

#             records.append({
#                 "uhid": patient.uhid,
#                 "name": patient.name,
#                 "age": patient.age,
#                 "gender": patient.gender,
#                 "bp": bp_value,
#                 "temp": consultation.v_temp if consultation else "",
#                 "spo2": consultation.v_spo2 if consultation else "",
#                 "pulse": consultation.v_pulse if consultation else "",
#                 "rr": consultation.v_rr if consultation else "",
#                 "provisional_dx": consultation.provisional_dx if consultation else "",
#                 "drugs": drugs_display
#             })

#     # Pass first UHID to template for Back button
#     back_uhid = records[0]["uhid"] if records else None

#     return render_template("view_records.html", records=records, back_uhid=back_uhid)

@app.route("/view_records", methods=["GET", "POST"])
@login_required
@require_roles("Doctor")
def view_records():
    search_query = request.args.get("q", "").strip()

    query = Patient.query
    if search_query:
        query = query.filter(
            (Patient.uhid.ilike(f"%{search_query}%")) |
            (Patient.name.ilike(f"%{search_query}%"))
        )

    patients = query.all()
    records = []

    for patient in patients:
        # Fetch all consultations for this patient
        consultations = Consultation.query.filter_by(patient_id=patient.id)\
                                         .order_by(Consultation.created_at.desc())\
                                         .all()
        # Fetch all prescriptions for this patient
        prescriptions = Prescription.query.filter_by(patient_id=patient.id)\
                                         .order_by(Prescription.created_at.desc())\
                                         .all()
        
        if consultations:
            # Existing logic for patients with consultations
            for cons in consultations:
                # Find the prescription closest to this consultation
                rx = next((p for p in prescriptions if p.consultation_id == cons.id), None)

                bp_value = cons.v_bp if cons.v_bp else ""
                drugs_display = "\n".join([line.strip() for line in rx.drugs.split("\n")]) if rx and rx.drugs else ""

                records.append({
                    "uhid": patient.uhid,
                    "name": patient.name,
                    "age": patient.age,
                    "gender": patient.gender,
                    "bp": bp_value,
                    "temp": cons.v_temp,
                    "spo2": cons.v_spo2,
                    "pulse": cons.v_pulse,
                    "rr": cons.v_rr,
                    "provisional_dx": cons.provisional_dx,
                    "cc": cons.cc,
                    "pmh": cons.pmh,
                    "pmxh": cons.pmxh,
                    "drugs": drugs_display,
                    "created_at": cons.created_at
                })
        else:
            # Fallback for patients with NO consultations
            records.append({
                "uhid": patient.uhid,
                "name": patient.name,
                "age": patient.age,
                "gender": patient.gender,
                "bp": "",
                "temp": "",
                "spo2": "",
                "pulse": "",
                "rr": "",
                "provisional_dx": "",
                "cc": "",
                "pmh": "",
                "pmxh": "",
                "drugs": "",
                "created_at": None  # Patients with no consultations will appear at the bottom
            })

    # Sort records by consultation date descending, None dates go to bottom
    records.sort(key=lambda x: x["created_at"] if x["created_at"] else datetime.min, reverse=True)

    back_uhid = records[0]["uhid"] if records else None

    return render_template("view_records.html", records=records, back_uhid=back_uhid)








# ----------------- API: Get patient details by UHID using API key -----------------
@app.route('/api/get_patient/<string:uhid>', methods=['GET'])
def api_get_patient(uhid):
    # API Key check
    api_key = request.headers.get("X-API-Key")
    if api_key != "genop-12345":   # <-- your API key
        return jsonify({"error": "Unauthorized"}), 401

    patient = Patient.query.filter_by(uhid=uhid).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    # Get latest prescription
    prescription = Prescription.query.filter_by(patient_id=patient.id).order_by(Prescription.created_at.desc()).first()

    if not prescription:
        return jsonify({
            "uhid": patient.uhid,
            "chief_complaints": "",
            "diagnosis": "",
            "drugs": []
        })

    # Split drugs by newline for separate rows
    drugs_list = prescription.drugs.split("\n") if prescription.drugs else []

    return jsonify({
        "uhid": patient.uhid,
        "chief_complaints": prescription.complaints,
        "diagnosis": prescription.diagnosis,
        "drugs": drugs_list
    })






# ---------- IT Exec: Analytics ----------
@app.route('/it_dashboard')
@login_required
@require_roles('IT Exec')
def it_dashboard():
    patients_count = Patient.query.count()
    labs_pending = LabRequest.query.filter(LabRequest.status != 'Completed').count()
    labs_done = LabRequest.query.filter(LabRequest.status == 'Completed').count()
    rx_count = Prescription.query.count()
    return render_template('it_dashboard.html',
                           patients_count=patients_count,
                           labs_pending=labs_pending,
                           labs_done=labs_done,
                           rx_count=rx_count)

# ---------- Utilities ----------
@app.context_processor
def inject_user():
    return {"current_user": current_user()}

# ----------------- Run -----------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)