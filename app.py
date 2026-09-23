import csv
import io
import os
import sqlite3
import uuid
import traceback
from datetime import datetime, timedelta
from functools import wraps

from sqlalchemy import inspect, text

from flask import (
    Flask, abort, flash, jsonify, redirect,
    request, send_file, url_for, Response, render_template,
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required,
    login_user, logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import qrcode

# ─── Configuration ───
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "maintenance")
PROFILE_PIC_FOLDER = os.path.join(BASE_DIR, "static", "profile_pics")
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROFILE_PIC_FOLDER"] = PROFILE_PIC_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

ROLES = ["ADMIN", "MANAGER", "SUPERVISOR", "TECHNICIAN", "MAINTENANCE STAFF", "EMPLOYEE", "DEPARTMENT"]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx"}


# ══════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(30), default="EMPLOYEE", nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    profile_pic = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class Floor(db.Model):
    __tablename__ = "floors"
    id = db.Column(db.Integer, primary_key=True)
    floor_number = db.Column(db.Integer, unique=True, nullable=False)


class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    floor = db.Column(db.Integer, nullable=False)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(30), default="Available")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Area(db.Model):
    __tablename__ = "areas"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class WorkingItem(db.Model):
    __tablename__ = "working_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)


class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    job_title = db.Column(db.String(120))
    department = db.Column(db.String(80), default="Engineering")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MaintenanceRequest(db.Model):
    __tablename__ = "maintenance_requests"
    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(30), unique=True, nullable=False)
    location_type = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.Integer)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    working_item_id = db.Column(db.Integer, db.ForeignKey("working_items.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default="MEDIUM")
    status = db.Column(db.String(30), default="Pending")
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    due_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    completion_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    working_item = db.relationship("WorkingItem", foreign_keys=[working_item_id])
    category = db.relationship("Category", foreign_keys=[category_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    manager = db.relationship("User", foreign_keys=[manager_id])
    department = db.relationship("Department", foreign_keys=[department_id])

    @property
    def location_name(self):
        if self.location_type == "Room" and self.room:
            return f"Room {self.room.room_number}"
        if self.area:
            return self.area.name
        return "Unknown"

    @property
    def is_overdue(self):
        if self.status in ["Completed", "Verified", "Closed"]:
            return False
        return self.due_date and datetime.utcnow() > self.due_date


class WorkOrder(db.Model):
    __tablename__ = "work_orders"
    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(30), unique=True, nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default="Assigned")
    work_performed = db.Column(db.Text)
    labor_hours = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text)
    completion_photo = db.Column(db.String(255))
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])


class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"
    id = db.Column(db.Integer, primary_key=True)
    part_name = db.Column(db.String(120), unique=True, nullable=False)
    quantity = db.Column(db.Float, default=0)
    minimum_stock = db.Column(db.Float, default=5)
    unit = db.Column(db.String(20), default="pcs")


class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(20), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    object_type = db.Column(db.String(100))
    object_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")


class StatusHistory(db.Model):
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    status = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)

    user = db.relationship("User")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def log_audit(action, object_type=None, object_id=None):
    db.session.add(AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action, object_type=object_type,
        object_id=str(object_id) if object_id else None,
    ))


def notify(user_ids, title, message):
    for uid in set(user_ids):
        if uid:
            db.session.add(Notification(user_id=uid, title=title, message=message))


def log_status(request_id, status, notes=None):
    db.session.add(StatusHistory(
        request_id=request_id, status=status, notes=notes,
        user_id=current_user.id if current_user.is_authenticated else None,
    ))


def gen_request_no():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def gen_wo_no():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.context_processor
def inject_globals():
    unread = 0
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return dict(unread_notifications=unread, now=datetime.utcnow())


# ══════════════════════════════════════════════════════════════
# DATABASE SCHEMA MIGRATION (ትክክለኛው መፍትሔ)
# ══════════════════════════════════════════════════════════════
def ensure_database_schema():
    with app.app_context():
        try:
            db.create_all()
            inspector = inspect(db.engine)
            if "maintenance_requests" not in inspector.get_table_names():
                print("⚠️ maintenance_requests missing")
                return

            existing = {c["name"] for c in inspector.get_columns("maintenance_requests")}
            additions = {
                "department_id": "ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER",
                "manager_id": "ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER",
                "completion_note": "ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT",
                "completed_date": "ALTER TABLE maintenance_requests ADD COLUMN completed_date DATETIME",
            }

            for col, sql in additions.items():
                if col not in existing:
                    with db.engine.begin() as conn:
                        conn.execute(text(sql))
                    print(f"✅ Added column: {col}")

            print("✅ Schema OK")
        except Exception as e:
            print(f"⚠️ Schema error: {e}")


# ══════════════════════════════════════════════════════════════
# SEED DATA
# ══════════════════════════════════════════════════════════════
def seed_data():
    for name in ["Housekeeping", "Front Office", "Engineering", "Food & Beverage",
                 "Administration", "Security", "Maintenance", "Other"]:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))

    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))

    if Room.query.count() == 0:
        for n in range(201, 301):
            fl = 2 if n <= 225 else 3 if n <= 250 else 4 if n <= 275 else 5
            db.session.add(Room(floor=fl, room_number=str(n), status="Available"))

    for name, dept in [("Buduchalley", "F&B"), ("Sillanto", "N/A"), ("Fura", "N/A"),
                       ("Executive", "N/A"), ("Mitima", "N/A"), ("Odako", "N/A"),
                       ("Gudumale", "N/A"), ("Bubble", "N/A"), ("Bubbles", "N/A"),
                       ("Fura Corridor", "N/A"), ("Executive Meeting Room", "N/A"),
                       ("Counter", "N/A")]:
        if not Area.query.filter_by(name=name).first():
            db.session.add(Area(name=name, department=dept))

    for c in ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry",
              "Civil", "Safety", "General", "Other"]:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    for i in ["Light", "Switch", "Window", "Door Key", "Door Lock", "Paint",
              "Mirror", "Drainage Cover", "Frame", "Background Frame",
              "Spot Light", "Plumbing", "AC", "Electrical", "Other"]:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    for eid, name, title in [
        (1, "ተስፋሁን ነከረ", "General Mechanic"),
        (2, "ቸርነት አሞና", "General Mechanic"),
        (3, "ስምዖን ዮሐንስ", "General Mechanic"),
        (4, "አበባየሁ ክፍሌ", "Supervisor"),
        (5, "አሚር አወል", "Manager"),
    ]:
        if not Employee.query.get(eid):
            db.session.add(Employee(id=eid, name=name, job_title=title, department="Engineering"))

    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN",
                 email="admin@rorihotel.local")
        u.set_password("admin123")
        db.session.add(u)

    for s in [
        {"u": "amir", "n": "አሚር አወል", "r": "MANAGER"},
        {"u": "abebayhu", "n": "አበባየሁ ክፍሌ", "r": "SUPERVISOR"},
        {"u": "tesfahun", "n": "ተስፋሁን ነከረ", "r": "TECHNICIAN"},
        {"u": "simon", "n": "ስምዖን ዮሐንስ", "r": "TECHNICIAN"},
        {"u": "chernet", "n": "ቸርነት አሞና", "r": "TECHNICIAN"},
        {"u": "housekeeping", "n": "Housekeeping Dept", "r": "DEPARTMENT"},
        {"u": "employee1", "n": "Test Employee", "r": "EMPLOYEE"},
    ]:
        if not User.query.filter_by(username=s["u"]).first():
            usr = User(username=s["u"], full_name=s["n"], role=s["r"])
            usr.set_password("123456")
            db.session.add(usr)

    db.session.commit()
    print("✅ Seed data loaded")


# ══════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.active:
            login_user(user)
            log_audit("Login", "User", user.id)
            db.session.commit()
            return redirect(url_for("dashboard"))
        flash("የተሳሳተ መለያ ስም ወይም የይለፍ ቃል", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "").strip()
        current_user.email = request.form.get("email", "").strip()
        current_user.phone = request.form.get("phone", "").strip()
        new_pass = request.form.get("new_password", "").strip()
        if new_pass:
            current_user.set_password(new_pass)
        db.session.commit()
        flash("መረጃዎ ተዘምኗል", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=current_user)


@app.route("/dashboard")
@login_required
def dashboard():
    total = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter_by(priority="URGENT").count()

    return render_template("dashboard.html",
        total=total, pending=pending, in_progress=in_progress,
        completed=completed, overdue=overdue, urgent=urgent)


@app.route("/requests")
@login_required
def requests_list():
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN"]:
        reqs = MaintenanceRequest.query.filter_by(assigned_to_id=current_user.id)\
            .order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        reqs = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("requests_list.html", requests=reqs)


@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def new_request():
    if request.method == "POST":
        loc_type = request.form.get("location_type")
        room_id = request.form.get("room_id", type=int)
        area_id = request.form.get("area_id", type=int)
        item_id = request.form.get("working_item_id", type=int)
        cat_id = request.form.get("category_id", type=int)
        dept_id = request.form.get("department_id", type=int)
        desc = request.form.get("description", "").strip()
        prio = request.form.get("priority", "MEDIUM")

        if loc_type == "Room":
            rm = Room.query.get(room_id)
            if not rm or not (201 <= int(rm.room_number) <= 300):
                flash("ልክ ያልሆነ ክፍል", "danger")
                return redirect(url_for("new_request"))
            floor, area_id = rm.floor, None
        else:
            ar = Area.query.get(area_id)
            if not ar:
                flash("ልክ ያልሆነ ቦታ", "danger")
                return redirect(url_for("new_request"))
            floor, room_id = None, None

        if not desc:
            flash("መግለጫ ያስፈልጋል", "danger")
            return redirect(url_for("new_request"))

        due = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio, 24))
        req = MaintenanceRequest(
            request_no=gen_request_no(), location_type=loc_type, floor=floor,
            room_id=room_id, area_id=area_id, working_item_id=item_id,
            category_id=cat_id, department_id=dept_id, description=desc,
            priority=prio, status="Pending", requested_by_id=current_user.id,
            due_date=due,
        )
        db.session.add(req)
        db.session.flush()
        log_status(req.id, "Pending", "Request submitted")
        log_audit("Create", "MaintenanceRequest", req.id)

        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify([u.id for u in managers], "አዲስ ጥያቄ", f"ጥያቄ {req.request_no} በ {req.location_name}")
        db.session.commit()
        flash("✅ ጥያቄዎ ተልኳል!", "success")
        return redirect(url_for("requests_list"))

    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    cats = Category.query.order_by(Category.name).all()
    depts = Department.query.order_by(Department.name).all()

    return render_template("request_form.html",
        rooms=rooms, areas=areas, items=items, categories=cats, departments=depts)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    history = StatusHistory.query.filter_by(request_id=req.id)\
        .order_by(StatusHistory.timestamp.desc()).all()
    return render_template("request_detail.html", request=req, history=history)


@app.route("/requests/<int:req_id>/approve")
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    r = MaintenanceRequest.query.get_or_404(req_id)
    if r.status == "Pending":
        r.status = "Approved"
        log_status(r.id, "Approved", f"Approved by {current_user.full_name}")
        notify([r.requested_by_id], "ጸድቋል", f"ጥያቄ {r.request_no}")
        db.session.commit()
        flash("ጥያቄው ጸድቋል", "success")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN"]:
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    return render_template("workorders_list.html", workorders=wos)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    return render_template("workorder_detail.html", workorder=wo)


@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(50).all()
    return render_template("notifications.html", notifications=notifs)


@app.route("/notifications/<int:n_id>/read")
@login_required
def mark_read(n_id):
    n = Notification.query.get_or_404(n_id)
    if n.user_id == current_user.id:
        n.is_read = True
        db.session.commit()
    return redirect(url_for("notifications"))


@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html")


@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel", "short_name": "RoriMaint", "start_url": "/"})


@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('install',e=>self.skipWaiting());",
                    mimetype="application/javascript")


@app.route("/logo.png")
def logo():
    p = os.path.join(app.root_path, "static", "logo.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return Response("", mimetype="image/png")


@app.errorhandler(403)
def e403(e):
    return render_template("error.html", code=403,
        message="ፍቃድ የለዎትም"), 403


@app.errorhandler(404)
def e404(e):
    return render_template("error.html", code=404,
        message="ገጹ አልተገኘም"), 404


@app.errorhandler(500)
def e500(e):
    tb = traceback.format_exc()
    print("❌ 500:", tb)
    return render_template("error.html", code=500,
        message="የስርዓት ስህተት"), 500


# ══════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════
with app.app_context():
    db.create_all()
    ensure_database_schema()
    seed_data()
    print("🚀 App initialized")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)