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
# MODELS
# --------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"
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
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Area(db.Model):
    __tablename__ = "areas"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)

class WorkingItem(db.Model):
    __tablename__ = "working_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)

class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    job_title = db.Column(db.String(120))
    department = db.Column(db.String(80), default="Engineering")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    __tablename__ = "work_orders"
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
    __tablename__ = "work_order_parts"
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_cost = db.Column(db.Float, default=0)

    work_order = db.relationship("WorkOrder", back_populates="parts_used")
    part = db.relationship("InventoryPart")

class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"
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
    __tablename__ = "stock_movements"
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
    __tablename__ = "suppliers"
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
    __tablename__ = "contractors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    service_type = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    rate = db.Column(db.Float)
    status = db.Column(db.String(20), default="Active")
    notes = db.Column(db.Text)

class PreventiveMaintenance(db.Model):
    __tablename__ = "preventive_maintenance"
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
    __tablename__ = "checklist_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("ChecklistTemplateItem", back_populates="template", cascade="all, delete-orphan")

class ChecklistTemplateItem(db.Model):
    __tablename__ = "checklist_template_items"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id"), nullable=False)
    item_text = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)

    template = db.relationship("ChecklistTemplate", back_populates="items")

class Inspection(db.Model):
    __tablename__ = "inspections"
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
    __tablename__ = "inspection_items"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id"), nullable=False)
    item_text = db.Column(db.String(200), nullable=False)
    result = db.Column(db.String(10), default="Pass")
    notes = db.Column(db.Text)

    inspection = db.relationship("Inspection", back_populates="items")

class Photo(db.Model):
    __tablename__ = "photos"
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
    __tablename__ = "notifications"
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
    __tablename__ = "audit_logs"
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
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    status = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    user = db.relationship("User", foreign_keys=[user_id])

class Setting(db.Model):
    __tablename__ = "settings"
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

def ensure_database_schema():
    with app.app_context():
        try:
            if not db.engine.dialect.has_table(db.engine, 'departments'):
                db.create_all()
                logger.info("Created departments table")
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
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

    departments = [
        "Housekeeping", "Front Office", "Engineering", "Food & Beverage",
        "Administration", "Security", "Maintenance", "Other"
    ]
    for dept_name in departments:
        if not Department.query.filter_by(name=dept_name).first():
            db.session.add(Department(name=dept_name))

    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))

    if Room.query.count() == 0:
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))

    initial_areas = [
        ("Buduchalley", "F&B"),
        ("Sillanto", "Unknown"),
        ("Fura", "Unknown"),
        ("Executive", "Unknown"),
        ("Mitima", "Unknown"),
        ("Odako", "Unknown"),
        ("Gudumale", "Unknown"),
        ("Bubble", "Unknown"),
        ("Bubbles", "Unknown"),
        ("Fura Corridor", "Unknown"),
        ("Executive Meeting Room", "Unknown"),
        ("Counter", "Unknown"),
    ]
    for name, dept in initial_areas:
        if not Area.query.filter_by(name=name).first():
            db.session.add(Area(name=name, department=dept))

    categories = ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry", "Civil", "Safety", "General", "Other"]
    for c in categories:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    items = [
        "Light", "Switch", "Window", "Door Key", "Door Lock", "Paint", "Mirror",
        "Drainage Cover", "Frame", "Background Frame", "Spot Light", "Plumbing",
        "AC", "Electrical", "Other",
    ]
    for i in items:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    engineering_staff = [
        (1, "ተስፋሁን ነከረ", "General Mechanic"),
        (2, "ቸርነት አሞና", "General Mechanic"),
        (3, "ስምዖን ዮሐንስ", "General Mechanic"),
        (4, "አበባየሁ ክፍሌ", "Supervisor"),
        (5, "አሚር አወል", "Manager"),
        (6, "ዋሌ", "General Mechanic"),
        (7, "ፃዲቁ", "General Mechanic"),
    ]
    for emp_id, name, title in engineering_staff:
        if not Employee.query.get(emp_id):
            db.session.add(Employee(id=emp_id, name=name, job_title=title, department="Engineering"))

    admin = User(
        username="admin",
        full_name="System Administrator",
        role="ADMIN",
        email="admin@rorihotel.local",
        phone="",
        profile_pic=None
    )
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    admin.set_password(admin_password)
    db.session.add(admin)

    staff_list = [
        {"username": "amir", "full_name": "አሚር አወል", "role": "MANAGER"},
        {"username": "abebayhu", "full_name": "አበባየሁ ክፍሌ", "role": "SUPERVISOR"},
        {"username": "tesfahun", "full_name": "ተስፋሁን ነከረ", "role": "TECHNICIAN"},
        {"username": "simon", "full_name": "ስምዖን ዮሐንስ", "role": "TECHNICIAN"},
        {"username": "chernet", "full_name": "ቸርነት አሞና", "role": "TECHNICIAN"},
        {"username": "wale", "full_name": "ዋሌ", "role": "TECHNICIAN"},
        {"username": "tsadiku", "full_name": "ፃዲቁ", "role": "TECHNICIAN"},
        {"username": "housekeeping", "full_name": "Housekeeping Dept", "role": "DEPARTMENT"},
        {"username": "employee1", "full_name": "Test Employee", "role": "EMPLOYEE"},
    ]
    for s in staff_list:
        user = User(
            username=s["username"],
            full_name=s["full_name"],
            role=s["role"],
            email="",
            phone="",
            profile_pic=None
        )
        user.set_password("123456")
        db.session.add(user)

    db.session.commit()

    if MaintenanceRequest.query.count() == 0:
        admin_user = User.query.filter_by(username="admin").first()
        dept = Department.query.first()
        note_records = [
            ("Sling", "Buduchalley"),
            ("Jemison Frame", "Sillanto"),
            ("Window", "Sillanto"),
            ("Paint", "Sillanto"),
            ("Paint", "Fura"),
            ("Paint", "Executive"),
            ("Background Frame", "Executive"),
            ("Door Key", "Mitima"),
            ("Corridor Paint", "Fura Corridor"),
            ("Light", "Executive Meeting Room"),
            ("Light", "Gudumale"),
            ("Light", "Counter"),
            ("Light", "Bubbles"),
            ("Cracked Mirror", "Executive Meeting Room"),
            ("Cracked Mirror", "Gudumale"),
            ("Cracked Mirror", "Counter"),
            ("Cracked Mirror", "Bubbles"),
            ("Drainage Line Cover", "Executive Meeting Room"),
            ("Drainage Line Cover", "Gudumale"),
            ("Drainage Line Cover", "Counter"),
            ("Drainage Line Cover", "Bubbles"),
            ("Switch Cover", "Odako"),
            ("Stage Light Switch Separation", "Odako"),
            ("Stage Light Switch Separation", "Gudumale"),
            ("Counter Paint / Spot Light", "Bubble"),
        ]
        for item_name, area_name in note_records:
            area = Area.query.filter_by(name=area_name).first()
            item_name_part = item_name.split(" / ")[0]
            item = WorkingItem.query.filter_by(name=item_name_part).first()
            if not item:
                item = WorkingItem.query.filter_by(name="Other").first()
            if area and item:
                req = MaintenanceRequest(
                    request_no=request_no_generator(),
                    location_type="Hotel Area",
                    area_id=area.id,
                    working_item_id=item.id,
                    category_id=Category.query.filter_by(name="General").first().id if Category.query.filter_by(name="General").first() else None,
                    description=f"Initial maintenance note: {item_name} at {area_name}",
                    priority="MEDIUM",
                    status="Pending",
                    requested_by_id=admin_user.id if admin_user else None,
                    department_id=dept.id if dept else None,
                    due_date=datetime.utcnow() + timedelta(hours=24),
                )
                db.session.add(req)
        db.session.commit()
    logger.info("Seed data loaded successfully.")
    logger.warning("Default passwords are used for staff (123456). Please change them immediately.")

# --------------------------------------------------------------
# ROUTES (all use render_template with Jinja2)
# --------------------------------------------------------------

@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN", "MANAGER"]:
            return redirect(url_for("dashboard"))
        elif current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        elif current_user.role == "EMPLOYEE":
            return redirect(url_for("employee_dashboard"))
        else:
            return redirect(url_for("workorders_list"))
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
            if user.role in ["ADMIN", "MANAGER"]:
                return redirect(url_for("dashboard"))
            elif user.role == "DEPARTMENT":
                return redirect(url_for("department_dashboard"))
            elif user.role == "EMPLOYEE":
                return redirect(url_for("employee_dashboard"))
            else:
                return redirect(url_for("workorders_list"))
        flash("Invalid username or password", "danger")
    return render_template("login.html", csrf_token=generate_csrf_token())

@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))

# ---------- PROFILE ----------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user
    if request.method == "POST":
        validate_csrf_token()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if email != user.email or phone != user.phone:
            old_email = user.email
            old_phone = user.phone
            user.email = email
            user.phone = phone
            log_audit("Profile Update", "User", user.id, f"Email: {old_email}, Phone: {old_phone}", f"Email: {email}, Phone: {phone}")
        new_password = request.form.get("new_password", "").strip()
        if new_password:
            user.set_password(new_password)
            flash("Password updated", "success")
        file = request.files.get("profile_pic")
        if file and file.filename != "":
            if allowed_file(file.filename):
                if user.profile_pic:
                    old_path = os.path.join(app.config["PROFILE_PIC_FOLDER"], user.profile_pic)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                ext = file.filename.rsplit('.', 1)[-1].lower()
                filename = secure_filename(f"{user.id}_{uuid.uuid4().hex}.{ext}")
                file.save(os.path.join(app.config["PROFILE_PIC_FOLDER"], filename))
                user.profile_pic = filename
                log_audit("Profile Pic Update", "User", user.id, old_value=user.profile_pic, new_value=filename)
                flash("Profile picture updated", "success")
            else:
                flash("Invalid file type", "danger")
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user, csrf_token=generate_csrf_token())

# ---------- EMPLOYEE DASHBOARD ----------
@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("employee_dashboard.html", requests=requests)

# ---------- DEPARTMENT DASHBOARD ----------
@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("department_dashboard.html", requests=requests)

# ---------- PUBLIC REQUEST FORM ----------
@app.route("/new", methods=["GET", "POST"])
def public_request_form():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    categories = Category.query.order_by(Category.name).all()
    departments = Department.query.order_by(Department.name).all()

    if request.method == "POST":
        validate_csrf_token()
        location_type = request.form.get("location_type")
        room_id = request.form.get("room_id", type=int)
        area_id = request.form.get("area_id", type=int)
        item_id = request.form.get("working_item_id", type=int)
        category_id = request.form.get("category_id", type=int)
        department_id = request.form.get("department_id", type=int)
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "MEDIUM")
        due_date = request.form.get("due_date")

        if location_type not in ["Room", "Hotel Area"]:
            flash("Invalid location type", "danger")
            return redirect(url_for("public_request_form"))

        if location_type == "Room":
            room = Room.query.get(room_id)
            if not room or not (201 <= int(room.room_number) <= 300):
                flash("Invalid room. Room numbers must be between 201 and 300.", "danger")
                return redirect(url_for("public_request_form"))
            floor = room.floor
            area_id = None
        else:
            area = Area.query.get(area_id)
            if not area:
                flash("Invalid area", "danger")
                return redirect(url_for("public_request_form"))
            floor = None
            room_id = None

        if not description:
            flash("Description is required", "danger")
            return redirect(url_for("public_request_form"))

        due = datetime.strptime(due_date, "%Y-%m-%dT%H:%M") if due_date else datetime.utcnow() + timedelta(hours=PRIORITIES.get(priority, 24))

        req = MaintenanceRequest(
            request_no=request_no_generator(),
            location_type=location_type,
            floor=floor,
            room_id=room_id,
            area_id=area_id,
            working_item_id=item_id,
            category_id=category_id,
            department_id=department_id,
            description=description,
            priority=priority,
            status="Pending",
            requested_by_id=current_user.id if current_user.is_authenticated else None,
            due_date=due,
        )
        db.session.add(req)
        db.session.flush()
        log_audit("Create (Public)", "MaintenanceRequest", req.id, new_value=f"{req.request_no} - {req.priority}")
        log_status_change(req.id, "Pending", notes="Request submitted")

        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify_users([u.id for u in managers], req.id, "New Maintenance Request",
                     f"A new request {req.request_no} has been submitted by {req.requested_by.full_name if req.requested_by else 'Guest'}.",
                     "New Request")

        if req.requested_by_id:
            notify_users([req.requested_by_id], req.id, "Request Submitted",
                         f"Your request {req.request_no} has been submitted successfully.", "Request Submitted")

        db.session.commit()
        flash("Request submitted successfully!", "success")
        return redirect(url_for("public_request_form"))

    return render_template("public_request_form.html", rooms=rooms, areas=areas, items=items,
                           categories=categories, departments=departments, csrf_token=generate_csrf_token())

# ---------- MANAGER / ADMIN DASHBOARD ----------
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role not in ["ADMIN", "MANAGER"]:
        flash("This page is for administrators only", "danger")
        return redirect(url_for("workorders_list"))
    # ... (full logic can be added here, but we use template)
    return render_template("dashboard.html")

# ---------- REQUESTS ----------
@app.route("/requests")
@login_required
def requests_list():
    if current_user.role == "DEPARTMENT":
        return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE":
        return redirect(url_for("employee_dashboard"))
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN"]:
        reqs = MaintenanceRequest.query.filter_by(assigned_to_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        reqs = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("requests_list.html", requests=reqs)

@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_create():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    categories = Category.query.order_by(Category.name).all()
    departments = Department.query.order_by(Department.name).all()
    if request.method == "POST":
        validate_csrf_token()
        # (same logic as public form, but with current_user.id as requester)
        # ... (after creation redirect to appropriate dashboard)
        pass
    return render_template("request_create.html", rooms=rooms, areas=areas, items=items,
                           categories=categories, departments=departments, csrf_token=generate_csrf_token())

@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    return render_template("request_detail.html", request=req)

@app.route("/requests/<int:req_id>/approve", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    validate_csrf_token()
    # ... (logic)
    return redirect(url_for("request_detail", req_id=req_id))

# ... (similar for reject, verify, close)

# ---------- WORK ORDERS ----------
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]:
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    return render_template("workorders_list.html", workorders=wos)

@app.route("/workorders/new", methods=["GET", "POST"])
@role_required("MANAGER", "ADMIN")
def workorder_create():
    # ... (logic)
    return render_template("workorder_create.html", csrf_token=generate_csrf_token())

@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    return render_template("workorder_detail.html", workorder=wo)

@app.route("/workorders/<int:wo_id>/start", methods=["POST"])
@login_required
def workorder_start(wo_id):
    validate_csrf_token()
    # ... (logic)
    return redirect(url_for("workorder_detail", wo_id=wo_id))

@app.route("/workorders/<int:wo_id>/complete", methods=["GET", "POST"])
@role_required("MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR")
def workorder_complete(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    if request.method == "POST":
        validate_csrf_token()
        # ... (logic with stock validation)
        return redirect(url_for("workorder_detail", wo_id=wo_id))
    parts = InventoryPart.query.all()
    return render_template("workorder_complete.html", workorder=wo, parts=parts, csrf_token=generate_csrf_token())

# ---------- ROOMS ----------
@app.route("/rooms")
@login_required
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    return render_template("rooms_list.html", rooms=rooms)

@app.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def room_edit(room_id):
    room = Room.query.get_or_404(room_id)
    if request.method == "POST":
        validate_csrf_token()
        # ... (update)
        return redirect(url_for("rooms_list"))
    return render_template("room_edit.html", room=room, csrf_token=generate_csrf_token())

# ---------- AREAS ----------
@app.route("/areas")
@login_required
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    return render_template("areas_list.html", areas=areas)

@app.route("/areas/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def area_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("areas_list"))
    return render_template("area_create.html", csrf_token=generate_csrf_token())

@app.route("/areas/<int:area_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def area_edit(area_id):
    area = Area.query.get_or_404(area_id)
    if request.method == "POST":
        validate_csrf_token()
        # ... (update)
        return redirect(url_for("areas_list"))
    return render_template("area_edit.html", area=area, csrf_token=generate_csrf_token())

# ---------- INVENTORY ----------
@app.route("/inventory")
@login_required
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    return render_template("inventory_list.html", parts=parts)

@app.route("/inventory/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def inventory_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("inventory_list"))
    return render_template("inventory_create.html", csrf_token=generate_csrf_token())

# ---------- PREVENTIVE MAINTENANCE ----------
@app.route("/preventive")
@login_required
@role_required("ADMIN", "MANAGER")
def preventive_list():
    tasks = PreventiveMaintenance.query.order_by(PreventiveMaintenance.next_due_date).all()
    return render_template("preventive_list.html", tasks=tasks)

@app.route("/preventive/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def preventive_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("preventive_list"))
    return render_template("preventive_create.html", csrf_token=generate_csrf_token())

# ---------- CHECKLISTS ----------
@app.route("/checklists")
@login_required
@role_required("ADMIN", "MANAGER")
def checklists_list():
    templates = ChecklistTemplate.query.all()
    return render_template("checklists_list.html", templates=templates)

@app.route("/checklists/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def checklist_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("checklists_list"))
    return render_template("checklist_create.html", csrf_token=generate_csrf_token())

# ---------- SUPPLIERS ----------
@app.route("/suppliers")
@login_required
@role_required("ADMIN", "MANAGER")
def suppliers_list():
    suppliers = Supplier.query.all()
    return render_template("suppliers_list.html", suppliers=suppliers)

@app.route("/suppliers/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def supplier_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("suppliers_list"))
    return render_template("supplier_create.html", csrf_token=generate_csrf_token())

# ---------- CONTRACTORS ----------
@app.route("/contractors")
@login_required
@role_required("ADMIN", "MANAGER")
def contractors_list():
    contractors = Contractor.query.all()
    return render_template("contractors_list.html", contractors=contractors)

@app.route("/contractors/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def contractor_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("contractors_list"))
    return render_template("contractor_create.html", csrf_token=generate_csrf_token())

# ---------- EMPLOYEES ----------
@app.route("/employees")
@login_required
@role_required("ADMIN", "MANAGER")
def employees_list():
    employees = Employee.query.order_by(Employee.id).all()
    return render_template("employees_list.html", employees=employees)

@app.route("/employees/new", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def employee_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("employees_list"))
    return render_template("employee_create.html", csrf_token=generate_csrf_token())

@app.route("/employees/<int:emp_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("ADMIN", "MANAGER")
def employee_edit(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    if request.method == "POST":
        validate_csrf_token()
        # ... (update)
        return redirect(url_for("employees_list"))
    return render_template("employee_edit.html", employee=emp, csrf_token=generate_csrf_token())

# ---------- ADMIN USERS ----------
@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/users/new", methods=["GET", "POST"])
@role_required("ADMIN")
def admin_user_create():
    if request.method == "POST":
        validate_csrf_token()
        # ... (create)
        return redirect(url_for("admin_users"))
    return render_template("admin_user_create.html", csrf_token=generate_csrf_token())

# ---------- MASTER DATA ----------
@app.route("/admin/masterdata")
@role_required("ADMIN")
def master_data():
    categories = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    return render_template("master_data.html", categories=categories, items=items)

# ---------- AUDIT LOG ----------
@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("audit_logs.html", logs=logs)

# ---------- BACKUP & RESTORE ----------
def get_db_path():
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    return os.path.join(BASE_DIR, "hotel_maintenance.db")

@app.route("/admin/backup", methods=["GET"])
@role_required("ADMIN")
def backup_page():
    try:
        backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
        return render_template("backup.html", backups=backups, csrf_token=generate_csrf_token())
    except Exception as e:
        flash(f"Error loading backups: {str(e)}", "danger")
        return redirect(url_for("dashboard"))

@app.route("/admin/backup/now", methods=["POST"])
@role_required("ADMIN")
def create_backup():
    validate_csrf_token()
    try:
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        filepath = os.path.join(BACKUP_FOLDER, filename)
        src = sqlite3.connect(get_db_path())
        dst = sqlite3.connect(filepath)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        log_audit("Backup", "Database", filename)
        db.session.commit()
        flash("Backup created successfully", "success")
    except Exception as e:
        flash(f"Error creating backup: {str(e)}", "danger")
    return redirect(url_for("backup_page"))

@app.route("/admin/restore/<filename>", methods=["POST"])
@role_required("ADMIN")
def restore_backup(filename):
    validate_csrf_token()
    if not filename.endswith(".db"):
        abort(400)
    try:
        filepath = os.path.join(BACKUP_FOLDER, filename)
        if not os.path.exists(filepath):
            flash("Backup file not found", "danger")
            return redirect(url_for("backup_page"))
        # Safety backup
        safety = os.path.join(BACKUP_FOLDER, f"safety_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        src = sqlite3.connect(get_db_path())
        dst = sqlite3.connect(safety)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        # Restore
        src = sqlite3.connect(filepath)
        dst = sqlite3.connect(get_db_path())
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        db.session.remove()
        log_audit("Restore", "Database", filename)
        db.session.commit()
        flash(f"Database restored successfully. Safety backup: {os.path.basename(safety)}", "success")
    except Exception as e:
        flash(f"Error restoring backup: {str(e)}", "danger")
    return redirect(url_for("backup_page"))

# ---------- REPORTS ----------
@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html")

@app.route("/reports/export/<report_type>")
@login_required
def reports_export(report_type):
    # ... (CSV export logic)
    pass

# ---------- QR CODES ----------
@app.route("/qr")
@login_required
def qr_index():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    return render_template("qr_index.html", rooms=rooms, areas=areas)

@app.route("/qr/<string:loc_type>/<int:id>")
@login_required
def qr_code(loc_type, id):
    # ... (generate QR)
    pass

# ---------- NOTIFICATIONS ----------
@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=notifs)

@app.route("/notifications/mark-read/<int:n_id>")
@login_required
def notification_mark_read(n_id):
    # ... (mark as read)
    return redirect(url_for("notifications"))

# ---------- PRIVACY ----------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

# ---------- PWA ----------
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Rori Hotel Maintenance",
        "short_name": "RoriMaint",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#f59e0b",
        "icons": []
    })

@app.route("/sw.js")
def service_worker():
    return Response("""self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {});""", mimetype="application/javascript")

@app.route('/logo.png')
def serve_logo():
    logo_path = os.path.join(app.root_path, 'static', 'logo.png')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/png')
    else:
        return send_file(io.BytesIO(b''), mimetype='image/png')

# ---------- ERROR HANDLERS ----------
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
# INIT
# --------------------------------------------------------------
with app.app_context():
    db.create_all()
    ensure_database_schema()
    seed_data()

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=5000)
