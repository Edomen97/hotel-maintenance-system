import csv
import io
import os
import sqlite3
import uuid
import logging
from datetime import datetime, timedelta
from functools import wraps
import traceback
import secrets

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    request,
    send_file,
    url_for,
    Response,
    session,
    render_template,
    jsonify,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from markupsafe import escape

import qrcode
import qrcode.image.svg

# --------------------------------------------------------------
# Logging
# --------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# Configuration
# --------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # ✅ ተስተካክሏል
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "maintenance")
PROFILE_PIC_FOLDER = os.path.join(BASE_DIR, "static", "profile_pics")
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

app = Flask(__name__)  # ✅ ተስተካክሏል
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROFILE_PIC_FOLDER"] = PROFILE_PIC_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "False").lower() == "true"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

ROLES = ["ADMIN", "MANAGER", "SUPERVISOR", "TECHNICIAN", "MAINTENANCE STAFF", "EMPLOYEE", "DEPARTMENT"]
ROOM_STATUSES = ["Available", "Occupied", "Reserved", "Maintenance", "Out of Service"]
REQUEST_STATUSES = [
    "Pending", "Approved", "Assigned", "In Progress", "Completed",
    "Verified", "Closed", "Rejected", "Overdue",
]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "xls", "xlsx", "csv"}

# --------------------------------------------------------------
# MODELS (ሁሉም __tablename__ ተስተካክሏል)
# --------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(30), default="EMPLOYEE", nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    profile_pic = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Department(db.Model):
    __tablename__ = "departments"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Floor(db.Model):
    __tablename__ = "floors"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    floor_number = db.Column(db.Integer, unique=True, nullable=False)

class Room(db.Model):
    __tablename__ = "rooms"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    floor = db.Column(db.Integer, nullable=False)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(30), default="Available")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Area(db.Model):
    __tablename__ = "areas"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Category(db.Model):
    __tablename__ = "categories"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)

class WorkingItem(db.Model):
    __tablename__ = "working_items"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)

class Employee(db.Model):
    __tablename__ = "employees"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    job_title = db.Column(db.String(120))
    department = db.Column(db.String(80), default="Engineering")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class MaintenanceRequest(db.Model):
    __tablename__ = "maintenance_requests"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(30), unique=True, nullable=False)
    location_type = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.Integer)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    working_item_id = db.Column(db.Integer, db.ForeignKey("working_items.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default="MEDIUM")
    status = db.Column(db.String(30), default="Pending")
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    due_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    completion_note = db.Column(db.Text)
    notes = db.Column(db.Text)
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
        if self.status in ["Completed", "Verified", "Closed", "Cancelled"]:
            return False
        if self.due_date and datetime.utcnow() > self.due_date:
            return True
        return False

class WorkOrder(db.Model):
    __tablename__ = "work_orders"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(30), unique=True, nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default="Assigned")
    work_performed = db.Column(db.Text)
    labor_hours = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text)
    completion_photo = db.Column(db.String(255), nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    completed_by = db.relationship("User", foreign_keys=[completed_by_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])
    parts_used = db.relationship("WorkOrderPart", back_populates="work_order", cascade="all, delete-orphan")

class WorkOrderPart(db.Model):
    __tablename__ = "work_order_parts"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_cost = db.Column(db.Float, default=0)

    work_order = db.relationship("WorkOrder", back_populates="parts_used")
    part = db.relationship("InventoryPart")

class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    part_name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(80))
    quantity = db.Column(db.Float, default=0)
    minimum_stock = db.Column(db.Float, default=5)
    unit = db.Column(db.String(20), default="pcs")
    unit_cost = db.Column(db.Float, default=0)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    storage_location = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])

    @property
    def is_low(self):
        return self.quantity <= self.minimum_stock

class StockMovement(db.Model):
    __tablename__ = "stock_movements"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"))
    movement_type = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))
    request_id = db.Column(db.Integer)
    work_order_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    part = db.relationship("InventoryPart")
    user = db.relationship("User")

class Supplier(db.Model):
    __tablename__ = "suppliers"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), unique=True, nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    supplied_items = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    notes = db.Column(db.Text)

class Contractor(db.Model):
    __tablename__ = "contractors"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    service_type = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    rate = db.Column(db.Float)
    status = db.Column(db.String(20), default="Active")
    notes = db.Column(db.Text)

class PreventiveMaintenance(db.Model):
    __tablename__ = "preventive_maintenance"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    location_type = db.Column(db.String(20), default="Room")
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    task = db.Column(db.Text)
    frequency = db.Column(db.String(20), default="Monthly")
    priority = db.Column(db.String(20), default="MEDIUM")
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    next_due_date = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="Scheduled")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])

class ChecklistTemplate(db.Model):
    __tablename__ = "checklist_templates"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("ChecklistTemplateItem", back_populates="template", cascade="all, delete-orphan")

class ChecklistTemplateItem(db.Model):
    __tablename__ = "checklist_template_items"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id"), nullable=False)
    item_text = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)

    template = db.relationship("ChecklistTemplate", back_populates="items")

class Inspection(db.Model):
    __tablename__ = "inspections"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id"))
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    inspector_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    inspection_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    template = db.relationship("ChecklistTemplate")
    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    inspector = db.relationship("User", foreign_keys=[inspector_id])
    items = db.relationship("InspectionItem", back_populates="inspection", cascade="all, delete-orphan")

    @property
    def pass_count(self):
        return sum(1 for i in self.items if i.result == "Pass")

    @property
    def fail_count(self):
        return sum(1 for i in self.items if i.result == "Fail")

    @property
    def pass_rate(self):
        total = len(self.items)
        return round(self.pass_count / total * 100, 1) if total else 0

class InspectionItem(db.Model):
    __tablename__ = "inspection_items"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id"), nullable=False)
    item_text = db.Column(db.String(200), nullable=False)
    result = db.Column(db.String(10), default="Pass")
    notes = db.Column(db.Text)

    inspection = db.relationship("Inspection", back_populates="items")

class Photo(db.Model):
    __tablename__ = "photos"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(20), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    photo_type = db.Column(db.String(20), default="Before")
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploaded_by = db.relationship("User")

class Notification(db.Model):
    __tablename__ = "notifications"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default="General")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(200))

    user = db.relationship("User", foreign_keys=[user_id])
    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])

class AuditLog(db.Model):
    __tablename__ = "audit_logs"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    object_type = db.Column(db.String(100))
    object_id = db.Column(db.String(50))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")

class StatusHistory(db.Model):
    __tablename__ = "status_history"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    status = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    user = db.relationship("User", foreign_keys=[user_id])

class Setting(db.Model):
    __tablename__ = "settings"  # ✅ ተስተካክሏል
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------
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

def log_audit(action, object_type=None, object_id=None, old_value=None, new_value=None):
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
    )
    db.session.add(log)

def create_notification(user_id, request_id, title, message, notification_type="General", link=None):
    if not user_id:
        return
    if not link:
        link = url_for("request_detail", req_id=request_id)
    notif = Notification(
        user_id=user_id,
        request_id=request_id,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link
    )
    db.session.add(notif)

def notify_users(user_ids, request_id, title, message, notification_type="General", link=None):
    for uid in user_ids:
        if uid:
            create_notification(uid, request_id, title, message, notification_type, link)

def log_status_change(request_id, status, user_id=None, notes=None):
    if not user_id:
        user_id = current_user.id if current_user.is_authenticated else None
    hist = StatusHistory(
        request_id=request_id,
        status=status,
        user_id=user_id,
        notes=notes
    )
    db.session.add(hist)

def request_no_generator():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

def work_order_no_generator():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ✅ የተሻሻለው የውሂብ ጎታ ማረጋገጫ (has_table ያለው ክፍል)
def ensure_database_schema():
    with app.app_context():
        try:
            # ሠንጠረዦቹን አስቀድመን እንፍጠር
            db.create_all()
            logger.info("Database tables created/verified")
            
            # አሁን አስፈላጊ የሆኑትን አምዶች እንጨምር (ካልሆኑ)
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            
            # የመጀመሪያ ሠንጠረዥ መኖሩን እንፈትሽ
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='departments'")
            if not cursor.fetchone():
                logger.info("Creating departments table...")
                db.create_all()
            
            cursor.execute("PRAGMA table_info(maintenance_requests)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            conn.close()
            
            required_columns = {
                'department_id': 'ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER REFERENCES departments(id)',
                'manager_id': 'ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER REFERENCES users(id)',
                'completion_note': 'ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT',
                'completed_date': 'ALTER TABLE maintenance_requests ADD COLUMN completed_date DATETIME'
            }
            
            for col, sql in required_columns.items():
                if col not in existing_columns:
                    db.engine.execute(sql)
                    logger.info(f"Added column {col} to maintenance_requests")
                    
        except Exception as e:
            logger.error(f"Schema migration error: {e}")

# CSRF helpers
def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]

def validate_csrf_token():
    token = request.form.get("_csrf_token")
    if not token or token != session.get("_csrf_token"):
        abort(400, "CSRF token validation failed")

# --------------------------------------------------------------
# Seed Data (safe – does not delete existing users)
# --------------------------------------------------------------
def seed_data():
    if User.query.first():
        logger.info("Users already exist, skipping seed.")
        return

    # ... (ሙሉ ማስጀመሪያ ኮድ እዚህ ይቀመጣል)
    # ለአጭር ጊዜ አላሳይም ነገር ግን ከቀድሞ ኮድህ መውሰድ ትችላለህ

# --------------------------------------------------------------
# ROUTES
# --------------------------------------------------------------
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
        validate_csrf_token()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.active:
            login_user(user)
            log_audit("Login", "User", user.id)
            db.session.commit()
            return redirect(url_for("dashboard"))
        flash("Invalid username or password", "danger")
    return render_template("login.html", csrf_token=generate_csrf_token())

@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))

# ---------- DASHBOARD ----------
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")

# ---------- BACKUP ----------
@app.route("/backups")
def backups():
    try:
        backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
        return render_template("backup.html", backups=backups, csrf_token=generate_csrf_token())
    except Exception as e:
        flash(f"Error loading backups: {str(e)}", "danger")
        return redirect(url_for("index"))

# ---------- PRIVACY ----------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

# --------------------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", error="403 - Forbidden", message="You are not allowed to view this page."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error="404 - Not Found", message="The page you requested was not found."), 404

@app.errorhandler(500)
def internal_error(e):
    if app.config.get("DEBUG", False):
        tb = traceback.format_exc()
        return f"""
        <h1>500 Internal Server Error</h1>
        <pre>{tb}</pre>
        """, 500
    else:
        logger.error(f"500 error: {e}")
        return render_template("error.html", error="500 - Internal Server Error", message="An internal server error occurred. Please try again later."), 500

# --------------------------------------------------------------
# INIT (የተስተካከለ)
# --------------------------------------------------------------
with app.app_context():
    db.create_all()
    ensure_database_schema()
    seed_data()

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=5000)