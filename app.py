# app.py - Rori Hotel Maintenance Management System (Premium Dark Dashboard)
import csv, io, json, os, re, sqlite3, uuid, traceback
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text, inspect, func
from flask import (Flask, abort, flash, get_flashed_messages, jsonify, redirect,
                   render_template, render_template_string, request, send_file, url_for, Response)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "maintenance")
PROFILE_PIC_FOLDER = os.path.join(BASE_DIR, "static", "profile_pics")
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROFILE_PIC_FOLDER"] = PROFILE_PIC_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

ROLES = ["ADMIN", "MANAGER", "SUPERVISOR", "TECHNICIAN", "MAINTENANCE STAFF", "EMPLOYEE", "DEPARTMENT"]
ROOM_STATUSES = ["Available", "Occupied", "Reserved", "Maintenance", "Out of Service"]
REQUEST_STATUSES = ["Pending", "Approved", "Assigned", "In Progress", "Completed", "Verified", "Closed", "Rejected", "Overdue"]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png","jpg","jpeg","gif","pdf","doc","docx","xls","xlsx","csv"}
STAFF_ROLES = ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]

# ══════════════════════════════════════════ MODELS (UNCHANGED)
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(30), default="EMPLOYEE", nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    profile_pic = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    department = db.relationship("Department", foreign_keys=[department_id])
    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)

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

class DepartmentSignature(db.Model):
    __tablename__ = "department_signatures"
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), unique=True, nullable=False)
    authorized_name = db.Column(db.String(150), nullable=False)
    signature_data = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    department = db.relationship("Department", foreign_keys=[department_id])

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
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    deletion_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    awaiting_hk_approval = db.Column(db.Boolean, default=False)
    hk_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    hk_approved_at = db.Column(db.DateTime)
    hk_approval_status = db.Column(db.String(20))
    hk_signature_data = db.Column(db.Text)
    hk_approval_notes = db.Column(db.Text)
    signature_name = db.Column(db.String(150), nullable=True)
    signature_status = db.Column(db.String(30), default="SIGNED")
    signature_signed_at = db.Column(db.DateTime, nullable=True)
    signature_data = db.Column(db.Text, nullable=True)
    signature_department = db.Column(db.String(80), nullable=True)
    signature_verified = db.Column(db.Boolean, default=False)
    signature_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    working_item = db.relationship("WorkingItem", foreign_keys=[working_item_id])
    category = db.relationship("Category", foreign_keys=[category_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    manager = db.relationship("User", foreign_keys=[manager_id])
    department = db.relationship("Department", foreign_keys=[department_id])
    deleted_by = db.relationship("User", foreign_keys=[deleted_by_id])
    hk_approved_by = db.relationship("User", foreign_keys=[hk_approved_by_id])
    signature_user = db.relationship("User", foreign_keys=[signature_user_id])

    @property
    def location_name(self):
        if self.location_type == "Room" and self.room:
            return "Room " + str(self.room.room_number)
        if self.area: return self.area.name
        return "Unknown"

    @property
    def is_overdue(self):
        if self.status in ["Completed","Verified","Closed","Cancelled"]: return False
        if self.due_date and datetime.utcnow() > self.due_date: return True
        return False

class WorkOrder(db.Model):
    __tablename__ = "work_orders"
    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(30), unique=True, nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default="Pending")
    work_performed = db.Column(db.Text)
    labor_hours = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text)
    completion_photo = db.Column(db.String(255), nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    completed_date = db.Column(db.DateTime)
    verified_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    completed_by = db.relationship("User", foreign_keys=[completed_by_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])

class WorkOrderPart(db.Model):
    __tablename__ = "work_order_parts"
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_cost = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    part = db.relationship("InventoryPart", foreign_keys=[part_id])

class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"
    id = db.Column(db.Integer, primary_key=True)
    part_name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(80))
    quantity = db.Column(db.Float, default=0)
    minimum_stock = db.Column(db.Float, default=5)
    unit = db.Column(db.String(20), default="pcs")
    unit_cost = db.Column(db.Float, default=0)
    storage_location = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Active")
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])
    @property
    def is_low(self): return self.quantity <= self.minimum_stock

class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(20), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    photo_type = db.Column(db.String(20), default="Before")
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"))
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default="General")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(250))
    user = db.relationship("User", foreign_keys=[user_id])

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
    user = db.relationship("User")

class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), unique=True, nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    tax_number = db.Column(db.String(60))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Contractor(db.Model):
    __tablename__ = "contractors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    service_type = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    status = db.Column(db.String(20), default="Active")

class PreventiveMaintenance(db.Model):
    __tablename__ = "preventive_maintenance"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    task = db.Column(db.Text)
    frequency = db.Column(db.String(20), default="Monthly")
    priority = db.Column(db.String(20), default="MEDIUM")
    next_due_date = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="Scheduled")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChecklistTemplate(db.Model):
    __tablename__ = "checklist_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

# ══════════════════════════════════════════ HELPERS (UNCHANGED)
def role_required(*roles):
    def dec(fn):
        @wraps(fn)
        def wrap(*a, **kw):
            if not current_user.is_authenticated: return redirect(url_for("login"))
            if current_user.role not in roles: abort(403)
            return fn(*a, **kw)
        return wrap
    return dec

def is_manager(user):
    if not user or not user.is_authenticated: return False
    return user.role in ["MANAGER", "ADMIN"]

def log_audit(action, object_type=None, object_id=None, old_value=None, new_value=None):
    try:
        db.session.add(AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action, object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
        ))
    except Exception as e: print("Audit error: " + str(e))

def create_notification(user_id, request_id, title, message, ntype="General", link=None, work_order_id=None):
    if not user_id: return None
    recent = Notification.query.filter_by(user_id=user_id, request_id=request_id, notification_type=ntype).order_by(Notification.created_at.desc()).first()
    if recent and (datetime.utcnow() - recent.created_at).total_seconds() < 5: return recent
    n = Notification(user_id=user_id, request_id=request_id, work_order_id=work_order_id,
                     title=title, message=message, notification_type=ntype, link=link)
    db.session.add(n); return n

def notify_users(ids, request_id, title, message, ntype="General", link=None, work_order_id=None):
    for uid in ids:
        if uid: create_notification(uid, request_id, title, message, ntype, link, work_order_id)

def notify_assigned_staff(req, wo, staff_user):
    if not staff_user: return
    title = "📋 Assigned to you: " + str(wo.work_order_no)
    item_name = req.working_item.name if req.working_item else "N/A"
    msg = ("Request: " + str(req.request_no) + " | WO: " + str(wo.work_order_no) +
           " | Location: " + str(req.location_name) + " | Item: " + str(item_name) +
           " | Priority: " + str(req.priority))
    link = url_for("workorder_detail", wo_id=wo.id)
    create_notification(staff_user.id, req.id, title, msg, "Work Order Assigned", link, wo.id)

def log_status_change(request_id, status, user_id=None, notes=None):
    if not user_id:
        user_id = current_user.id if current_user.is_authenticated else None
    db.session.add(StatusHistory(request_id=request_id, status=status, user_id=user_id, notes=notes))

def request_no_generator():
    return "R-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()

def work_order_no_generator():
    return "WO-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()

def allowed_file(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_one(model, ident): return db.session.get(model, ident)
def get_or_404(model, ident):
    obj = db.session.get(model, ident)
    if obj is None: abort(404)
    return obj

def valid_email(v): return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v or ""))

def get_user_signature_profile(user):
    if not user or not user.is_authenticated or not user.department_id:
        return None
    return DepartmentSignature.query.filter_by(
        department_id=user.department_id, is_active=True
    ).first()

def validate_signature_for_user(user, signature_data):
    if not user or not user.is_authenticated:
        return False, "User not authenticated."
    if not user.department_id:
        return False, "Your account is not linked to a department. Contact admin."
    profile = get_user_signature_profile(user)
    if not profile:
        return False, "No authorized signature configured for your department. Contact admin."
    if not signature_data or not signature_data.strip():
        return False, "Digital signature is required. Your request cannot be submitted without a verified department signature."
    if not signature_data.startswith("data:image/png;base64,"):
        return False, "Invalid signature format."
    return True, None

def add_column_if_missing(table, column, sql):
    try:
        insp = inspect(db.engine)
        if table not in insp.get_table_names(): return False
        cols = [c["name"] for c in insp.get_columns(table)]
        if column not in cols:
            with db.engine.begin() as conn: conn.execute(text(sql))
            print("✅ Added " + column + " to " + table); return True
        return False
    except Exception as e:
        print("⚠️ Migration warn (" + table + "." + column + "): " + str(e)); return False

def ensure_database_schema():
    with app.app_context():
        try:
            db.create_all()
            pg = db.engine.dialect.name == "postgresql"
            dt = "TIMESTAMP" if pg else "DATETIME"
            bd = "DEFAULT FALSE" if pg else "DEFAULT 0"
            add_column_if_missing("maintenance_requests","department_id","ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER")
            add_column_if_missing("maintenance_requests","manager_id","ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER")
            add_column_if_missing("maintenance_requests","completion_note","ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT")
            add_column_if_missing("maintenance_requests","completed_date","ALTER TABLE maintenance_requests ADD COLUMN completed_date " + dt)
            add_column_if_missing("maintenance_requests","is_deleted","ALTER TABLE maintenance_requests ADD COLUMN is_deleted BOOLEAN " + bd)
            add_column_if_missing("maintenance_requests","deleted_at","ALTER TABLE maintenance_requests ADD COLUMN deleted_at " + dt)
            add_column_if_missing("maintenance_requests","deleted_by_id","ALTER TABLE maintenance_requests ADD COLUMN deleted_by_id INTEGER")
            add_column_if_missing("maintenance_requests","deletion_reason","ALTER TABLE maintenance_requests ADD COLUMN deletion_reason TEXT")
            add_column_if_missing("maintenance_requests","awaiting_hk_approval","ALTER TABLE maintenance_requests ADD COLUMN awaiting_hk_approval BOOLEAN " + bd)
            add_column_if_missing("maintenance_requests","hk_approved_by_id","ALTER TABLE maintenance_requests ADD COLUMN hk_approved_by_id INTEGER")
            add_column_if_missing("maintenance_requests","hk_approved_at","ALTER TABLE maintenance_requests ADD COLUMN hk_approved_at " + dt)
            add_column_if_missing("maintenance_requests","hk_approval_status","ALTER TABLE maintenance_requests ADD COLUMN hk_approval_status VARCHAR(20)")
            add_column_if_missing("maintenance_requests","hk_signature_data","ALTER TABLE maintenance_requests ADD COLUMN hk_signature_data TEXT")
            add_column_if_missing("maintenance_requests","hk_approval_notes","ALTER TABLE maintenance_requests ADD COLUMN hk_approval_notes TEXT")
            add_column_if_missing("maintenance_requests","signature_name","ALTER TABLE maintenance_requests ADD COLUMN signature_name VARCHAR(150)")
            add_column_if_missing("maintenance_requests","signature_status","ALTER TABLE maintenance_requests ADD COLUMN signature_status VARCHAR(30) DEFAULT 'SIGNED'")
            add_column_if_missing("maintenance_requests","signature_signed_at","ALTER TABLE maintenance_requests ADD COLUMN signature_signed_at " + dt)
            add_column_if_missing("maintenance_requests","signature_data","ALTER TABLE maintenance_requests ADD COLUMN signature_data TEXT")
            add_column_if_missing("maintenance_requests","signature_department","ALTER TABLE maintenance_requests ADD COLUMN signature_department VARCHAR(80)")
            add_column_if_missing("maintenance_requests","signature_verified","ALTER TABLE maintenance_requests ADD COLUMN signature_verified BOOLEAN " + bd)
            add_column_if_missing("maintenance_requests","signature_user_id","ALTER TABLE maintenance_requests ADD COLUMN signature_user_id INTEGER")
            add_column_if_missing("users","department_id","ALTER TABLE users ADD COLUMN department_id INTEGER")
            add_column_if_missing("notifications","work_order_id","ALTER TABLE notifications ADD COLUMN work_order_id INTEGER")
            add_column_if_missing("work_orders","completed_date","ALTER TABLE work_orders ADD COLUMN completed_date " + dt)
            add_column_if_missing("work_orders","verified_date","ALTER TABLE work_orders ADD COLUMN verified_date " + dt)
            add_column_if_missing("audit_logs","ip_address","ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(50)")
            add_column_if_missing("suppliers","email","ALTER TABLE suppliers ADD COLUMN email VARCHAR(120)")
            add_column_if_missing("suppliers","address","ALTER TABLE suppliers ADD COLUMN address TEXT")
            add_column_if_missing("suppliers","tax_number","ALTER TABLE suppliers ADD COLUMN tax_number VARCHAR(60)")
            add_column_if_missing("suppliers","notes","ALTER TABLE suppliers ADD COLUMN notes TEXT")
            if add_column_if_missing("suppliers","is_active","ALTER TABLE suppliers ADD COLUMN is_active BOOLEAN " + bd):
                with db.engine.begin() as conn:
                    conn.execute(text("UPDATE suppliers SET is_active = CASE WHEN status = 'Active' THEN TRUE ELSE FALSE END"))
            add_column_if_missing("suppliers","created_at","ALTER TABLE suppliers ADD COLUMN created_at " + dt)
            add_column_if_missing("suppliers","updated_at","ALTER TABLE suppliers ADD COLUMN updated_at " + dt)
            add_column_if_missing("inventory_parts","supplier_id","ALTER TABLE inventory_parts ADD COLUMN supplier_id INTEGER")
            print("✅ Schema OK")
        except Exception as e: print("⚠️ Schema error: " + str(e))

# ══════════════════════════════════════════ PREMIUM DARK DASHBOARD TEMPLATE
DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Central Dashboard | Rori Hotel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --rori-gold: #C5A059;
            --rori-gold-dark: #A8873F;
            --bg-primary: #0B0B12;
            --bg-secondary: #11111B;
            --bg-card: #151522;
            --bg-card-hover: #1B1B2A;
            --border-color: rgba(197,160,89,0.20);
            --text-primary: #FFFFFF;
            --text-secondary: #A7A7B3;
            --success: #22C55E;
            --warning: #F59E0B;
            --danger: #EF4444;
            --info: #38BDF8;
        }
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Inter',sans-serif;background:var(--bg-primary);min-height:100vh;color:var(--text-primary);padding-top:70px}
        
        /* Header */
        .navbar{background:var(--bg-secondary)!important;border-bottom:1px solid var(--border-color);padding:.75rem 1.5rem}
        .navbar-brand{font-weight:800;font-size:1.3rem;color:var(--rori-gold)!important}
        .nav-link-custom{color:var(--text-secondary)!important;padding:.5rem 1rem!important;border-radius:8px;font-size:.9rem;transition:all 0.2s}
        .nav-link-custom:hover, .nav-link-custom.active{background:rgba(197,160,89,0.1);color:var(--rori-gold)!important}
        
        /* Sidebar */
        .sidebar{position:fixed;top:70px;left:0;bottom:0;width:260px;background:var(--bg-secondary);border-right:1px solid var(--border-color);z-index:1000;transition:transform 0.3s ease;overflow-y:auto}
        .sidebar.collapsed{transform:translateX(-100%)}
        .sidebar-link{display:flex;align-items:center;padding:0.85rem 1.5rem;color:var(--text-secondary);text-decoration:none;transition:all 0.2s;border-left:3px solid transparent}
        .sidebar-link:hover, .sidebar-link.active{background:rgba(197,160,89,0.1);color:var(--rori-gold);border-left-color:var(--rori-gold)}
        .sidebar-link i{width:24px;text-align:center;margin-right:10px}
        
        /* Main Content */
        .main-content{margin-left:260px;padding:2rem;transition:margin-left 0.3s ease}
        .sidebar.collapsed ~ .main-content{margin-left:0}
        
        /* Cards */
        .card-premium{background:var(--bg-card);border:1px solid var(--border-color);border-radius:16px;padding:1.25rem;transition:transform 0.2s, border-color 0.2s}
        .card-premium:hover{transform:translateY(-2px);border-color:var(--rori-gold)}
        
        /* KPI */
        .kpi-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:16px;padding:1.25rem;text-align:center;transition:all 0.2s}
        .kpi-card:hover{border-color:var(--rori-gold)}
        .kpi-value{font-size:2rem;font-weight:800;color:var(--text-primary)}
        .kpi-label{font-size:.75rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px}
        
        /* Forms */
        .form-control-dark, .form-select-dark{background:var(--bg-secondary);border:1px solid var(--border-color);color:var(--text-primary);border-radius:8px}
        .form-control-dark:focus, .form-select-dark:focus{background:var(--bg-card);border-color:var(--rori-gold);color:var(--text-primary);box-shadow:0 0 0 3px rgba(197,160,89,0.15)}
        
        /* Tables */
        .table-dark-premium{color:var(--text-primary)}
        .table-dark-premium thead th{background:var(--bg-secondary);color:var(--rori-gold);border-bottom:1px solid var(--border-color);font-size:.75rem;text-transform:uppercase}
        .table-dark-premium td{border-color:var(--border-color);font-size:.85rem}
        .table-dark-premium tbody tr:hover{background:var(--bg-card-hover)}
        
        /* Alert Pulse */
        @keyframes pulse-gold{0%{box-shadow:0 0 0 0 rgba(197,160,89,0.7)}70%{box-shadow:0 0 0 10px rgba(197,160,89,0)}100%{box-shadow:0 0 0 0 rgba(197,160,89,0)}}
        .alert-pulse{animation:pulse-gold 2s infinite}
        
        /* Badges */
        .badge-gold{background:rgba(197,160,89,0.2);color:var(--rori-gold)}
        .badge-success{background:rgba(34,197,94,0.2);color:var(--success)}
        .badge-danger{background:rgba(239,68,68,0.2);color:var(--danger)}
        .badge-info{background:rgba(56,189,248,0.2);color:var(--info)}
        
        /* Mobile */
        @media(max-width:991px){
            .sidebar{transform:translateX(-100%)}
            .sidebar.show{transform:translateX(0)}
            .main-content{margin-left:0}
            .kpi-value{font-size:1.5rem}
        }
    </style>
</head>
<body>
    <!-- Header -->
    <nav class="navbar navbar-expand-lg fixed-top">
        <div class="container-fluid">
            <button class="btn btn-sm btn-outline-secondary d-lg-none me-2" onclick="toggleSidebar()"><i class="fas fa-bars"></i></button>
            <a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="fas fa-hotel"></i> RORI HOTEL</a>
            <div class="collapse navbar-collapse" id="nav">
                <div class="navbar-nav ms-auto align-items-center">
                    <a class="nav-link-custom position-relative" href="{{ url_for('notifications') }}">
                        <i class="fas fa-bell"></i>
                        <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger notif-badge" style="font-size:0.6rem;">
                            {{ Notification.query.filter_by(user_id=current_user.id, is_read=False).count() or 0 }}
                        </span>
                    </a>
                    <div class="dropdown">
                        <a class="nav-link-custom dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">
                            <i class="fas fa-user-circle"></i> {{ current_user.full_name or current_user.username }}
                        </a>
                        <ul class="dropdown-menu dropdown-menu-end" style="background:var(--bg-card);border:1px solid var(--border-color)">
                            <li><a class="dropdown-item text-light" href="{{ url_for('profile') }}"><i class="fas fa-user"></i> Profile</a></li>
                            <li><hr class="dropdown-divider" style="border-color:var(--border-color)"></li>
                            <li><a class="dropdown-item text-danger" href="{{ url_for('logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a></li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </nav>

    <!-- Sidebar -->
    <aside class="sidebar" id="sidebar">
        <a href="{{ url_for('dashboard') }}" class="sidebar-link active"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
        <a href="{{ url_for('requests_list') }}" class="sidebar-link"><i class="fas fa-clipboard-list"></i> Requests</a>
        <a href="{{ url_for('workorders_list') }}" class="sidebar-link"><i class="fas fa-tasks"></i> Work Orders</a>
        <a href="{{ url_for('workorders_list') }}" class="sidebar-link"><i class="fas fa-users-cog"></i> Staff Assignment</a>
        <a href="#" class="sidebar-link"><i class="fas fa-check-circle"></i> Completed Work</a>
        <a href="{{ url_for('inventory_list') }}" class="sidebar-link"><i class="fas fa-boxes"></i> Inventory</a>
        <a href="{{ url_for('notifications') }}" class="sidebar-link"><i class="fas fa-bell"></i> Notifications</a>
        <a href="{{ url_for('reports') }}" class="sidebar-link"><i class="fas fa-chart-bar"></i> Reports</a>
        {% if current_user.role in ['ADMIN', 'MANAGER'] %}
        <a href="{{ url_for('management_reports') }}" class="sidebar-link"><i class="fas fa-chart-line"></i> Management</a>
        {% endif %}
        <a href="#" class="sidebar-link"><i class="fas fa-cog"></i> Settings</a>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
        <!-- Page Title -->
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-3 mb-4">
            <div>
                <h2 style="color:var(--rori-gold);font-weight:800;margin:0"><i class="fas fa-shield-alt"></i> Maintenance Command Center</h2>
                <p style="color:var(--text-secondary);font-size:.85rem;margin:.25rem 0 0">Real-time maintenance operations and hotel service monitoring</p>
            </div>
            <a href="{{ url_for('request_create') }}" class="btn" style="background:var(--rori-gold);color:#000;font-weight:600"><i class="fas fa-plus-circle"></i> New Request</a>
        </div>

        <!-- New Request Alert -->
        <div id="newRequestAlert" class="card-premium mb-4" style="display: none; border-color: var(--rori-gold); background: rgba(197,160,89,0.05);">
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-3">
                <div>
                    <h5 class="mb-1" style="color: var(--rori-gold);"><i class="fas fa-bell fa-beat"></i> NEW MAINTENANCE REQUEST</h5>
                    <p class="mb-0" style="color:var(--text-secondary)">A new request has been submitted and requires your attention.</p>
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-sm btn-outline-light" onclick="acknowledgeAlert()"><i class="fas fa-check"></i> Acknowledge</button>
                </div>
            </div>
        </div>

        <!-- Sound Controls -->
        <div class="d-flex gap-2 align-items-center mb-4 flex-wrap">
            <span style="color:var(--text-secondary);font-size:0.85rem"><i class="fas fa-volume-up"></i> Notification Sound:</span>
            <button id="soundOn" class="btn btn-sm btn-outline-secondary" onclick="toggleSound(true)">ON</button>
            <button id="soundOff" class="btn btn-sm btn-outline-secondary" onclick="toggleSound(false)">OFF</button>
            <button class="btn btn-sm btn-outline-warning" onclick="testSound()"><i class="fas fa-play"></i> Test</button>
            <div id="audioEnableHint" class="ms-2" style="display:none;color:var(--warning);font-size:0.8rem"><i class="fas fa-info-circle"></i> Click anywhere to enable audio</div>
        </div>

        <!-- Filter Bar -->
        <form method="get" class="card-premium mb-4">
            <div class="row g-3">
                <div class="col-6 col-md-2"><label class="form-label" style="color:var(--text-secondary);font-size:0.8rem">From</label><input type="date" class="form-control-dark form-control" name="date_from" value="{{ filters.get('date_from','') }}"></div>
                <div class="col-6 col-md-2"><label class="form-label" style="color:var(--text-secondary);font-size:0.8rem">To</label><input type="date" class="form-control-dark form-control" name="date_to" value="{{ filters.get('date_to','') }}"></div>
                <div class="col-6 col-md-2"><label class="form-label" style="color:var(--text-secondary);font-size:0.8rem">Department</label>
                    <select class="form-select-dark form-select" name="department">
                        <option value="">All</option>
                        {% for d in all_departments %}<option value="{{ d.id }}" {% if filters.get('department') == d.id|string %}selected{% endif %}>{{ d.name }}</option>{% endfor %}
                    </select>
                </div>
                <div class="col-6 col-md-2"><label class="form-label" style="color:var(--text-secondary);font-size:0.8rem">Category</label>
                    <select class="form-select-dark form-select" name="category">
                        <option value="">All</option>
                        {% for c in all_categories %}<option value="{{ c.id }}" {% if filters.get('category') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                    </select>
                </div>
                <div class="col-6 col-md-2"><label class="form-label" style="color:var(--text-secondary);font-size:0.8rem">Status</label>
                    <select class="form-select-dark form-select" name="status">
                        <option value="">All</option>
                        {% for s in ['Pending','Approved','Assigned','In Progress','Completed','Verified','Closed','Rejected'] %}
                        <option value="{{ s }}" {% if filters.get('status') == s %}selected{% endif %}>{{ s }}</option>{% endfor %}
                    </select>
                </div>
                <div class="col-6 col-md-2 d-flex align-items-end gap-2">
                    <button class="btn flex-grow-1" style="background:var(--rori-gold);color:#000;font-weight:600" type="submit"><i class="fas fa-filter"></i> Apply</button>
                    <a class="btn btn-outline-secondary" href="{{ url_for('dashboard') }}">Reset</a>
                </div>
            </div>
        </form>

        <!-- KPI Cards -->
        <div class="row g-3 mb-4">
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-clipboard-list fa-2x mb-2" style="color:var(--rori-gold)"></i><div class="kpi-value">{{ kpis.total }}</div><div class="kpi-label">Total Requests</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-hourglass-half fa-2x mb-2" style="color:var(--warning)"></i><div class="kpi-value">{{ kpis.pending }}</div><div class="kpi-label">Pending</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-spinner fa-2x mb-2" style="color:var(--info)"></i><div class="kpi-value">{{ kpis.in_progress if 'in_progress' in kpis else 0 }}</div><div class="kpi-label">In Progress</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-circle-check fa-2x mb-2" style="color:var(--success)"></i><div class="kpi-value">{{ kpis.completed }}</div><div class="kpi-label">Completed</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-clipboard-check fa-2x mb-2" style="color:var(--info)"></i><div class="kpi-value">{{ kpis.verified if 'verified' in kpis else 0 }}</div><div class="kpi-label">Verified</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-exclamation-triangle fa-2x mb-2" style="color:var(--danger)"></i><div class="kpi-value">{{ urgent_count }}</div><div class="kpi-label">Urgent</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-clock fa-2x mb-2" style="color:var(--rori-gold)"></i><div class="kpi-value">{{ total_work_hours }}</div><div class="kpi-label">Total Work Hours</div></div></div>
            <div class="col-6 col-md-3 col-lg-1-5"><div class="kpi-card"><i class="fas fa-users fa-2x mb-2" style="color:var(--success)"></i><div class="kpi-value">{{ active_staff_count }}</div><div class="kpi-label">Staff Active</div></div></div>
        </div>

        <!-- Charts Row 1 -->
        <div class="row g-3 mb-4">
            <div class="col-lg-8">
                <div class="card-premium">
                    <h5 class="mb-3" style="color:var(--rori-gold)"><i class="fas fa-chart-area"></i> Maintenance Activity</h5>
                    <div style="position:relative;width:100%;height:300px"><canvas id="chartTrends"></canvas></div>
                </div>
            </div>
            <div class="col-lg-4">
                <div class="card-premium">
                    <h5 class="mb-3" style="color:var(--rori-gold)"><i class="fas fa-chart-pie"></i> Work Status</h5>
                    <div style="position:relative;width:100%;height:300px"><canvas id="chartStatus"></canvas></div>
                </div>
            </div>
        </div>

        <!-- Charts Row 2 -->
        <div class="row g-3 mb-4">
            <div class="col-lg-6">
                <div class="card-premium">
                    <h5 class="mb-3" style="color:var(--rori-gold)"><i class="fas fa-building"></i> Requests by Department</h5>
                    <div style="position:relative;width:100%;height:300px"><canvas id="chartDept"></canvas></div>
                </div>
            </div>
            <div class="col-lg-6">
                <div class="card-premium">
                    <h5 class="mb-3" style="color:var(--rori-gold)"><i class="fas fa-check-double"></i> Completion % by Dept</h5>
                    <div style="position:relative;width:100%;height:300px"><canvas id="chartDeptComp"></canvas></div>
                </div>
            </div>
        </div>

        <!-- Staff Workload & Completed Work -->
        <div class="row g-3 mb-4">
            <div class="col-lg-6">
                <div class="card-premium">
                    <h5 class="mb-3" style="color:var(--rori-gold)"><i class="fas fa-users-gear"></i> Staff Workload</h5>
                    {% if technician_workload|length > 0 %}
                    <div class="table-responsive">
                        <table class="table table-dark-premium table-hover">
                            <thead><tr><th>Staff</th><th>Assigned</th><th>In Progress</th><th>Completed</th><th>Avg Time</th></tr></thead>
                            <tbody>
                                {% for t in technician_workload %}
                                <tr>
                                    <td><strong>{{ t.name }}</strong><br><small style="color:var(--text-secondary)">{{ t.role }}</small></td>
                                    <td><span class="badge badge-info">{{ t.assigned }}</span></td>
                                    <td><span class="badge badge-gold">{{ t.in_progress }}</span></td>
                                    <td><span class="badge badge-success">{{ t.completed }}</span></td>
                                    <td>{{ t.avg_resolution }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    {% else %}
                    <div class="text-center py-4" style="color:var(--text-secondary)"><i class="fas fa-users fa-2x mb-2"></i><br>No technicians found</div>
                    {% endif %}
                </div>
            </div>
            <div class="col-lg-6">
                <div class="card-premium">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5 style="color:var(--rori-gold);margin:0"><i class="fas fa-check-circle"></i> Completed Work</h5>
                        <a href="{{ url_for('workorders_list') }}" class="btn btn-sm btn-outline-secondary" style="font-size:.75rem">View All</a>
                    </div>
                    {% if completed_work|length > 0 %}
                    <div class="table-responsive">
                        <table class="table table-dark-premium table-hover">
                            <thead><tr><th>Request</th><th>Task</th><th>Staff</th><th>Dept</th><th>Completed</th></tr></thead>
                            <tbody>
                                {% for w in completed_work %}
                                <tr>
                                    <td><a href="{{ url_for('workorder_detail', wo_id=w.id) }}" style="color:var(--rori-gold)">{{ w.work_order_no }}</a></td>
                                    <td>{{ w.work_performed[:20] + '...' if w.work_performed and w.work_performed|length > 20 else (w.work_performed or 'N/A') }}</td>
                                    <td>{{ w.completed_by.full_name if w.completed_by else 'N/A' }}</td>
                                    <td>{{ w.request.department.name if w.request and w.request.department else 'N/A' }}</td>
                                    <td style="font-size:.8rem">{{ w.completed_date.strftime('%b %d, %H:%M') if w.completed_date else 'N/A' }}</td>
                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    {% else %}
                    <div class="text-center py-4" style="color:var(--text-secondary)"><i class="fas fa-inbox fa-2x mb-2"></i><br>No completed work yet</div>
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- Recent Requests & Activity -->
        <div class="row g-3 mb-4">
            <div class="col-lg-8">
                <div class="card-premium">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5 style="color:var(--rori-gold);margin:0"><i class="fas fa-clock-rotate-left"></i> Recent Requests</h5>
                        <a href="{{ url_for('requests_list') }}" class="btn btn-sm btn-outline-secondary" style="font-size:.75rem">View All</a>
                    </div>
                    {% if recent_requests|length > 0 %}
                    <div class="table-responsive">
                        <table class="table table-dark-premium table-hover">
                            <thead><tr><th>Request</th><th>Dept</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th><th>Action</th></tr></thead>
                            <tbody>
                                {% for r in recent_requests %}
                                <tr>
                                    <td><a href="{{ url_for('request_detail', req_id=r.id) }}" style="color:var(--rori-gold);font-weight:600">{{ r.request_no }}</a></td>
                                    <td>{{ r.department.name if r.department else '—' }}</td>
                                    <td>{{ r.location_name }}</td>
                                    <td><span class="badge {{ 'badge-danger' if r.priority=='URGENT' else 'badge-gold' if r.priority=='HIGH' else 'badge-info' }}">{{ r.priority }}</span></td>
                                    <td><span class="badge {{ 'badge-success' if r.status in ['Completed','Verified'] else 'badge-gold' if r.status=='Pending' else 'badge-info' }}">{{ r.status }}</span></td>
                                    <td style="color:var(--text-secondary);font-size:.78rem">{{ r.created_at.strftime('%b %d') if r.created_at else '—' }}</td>
                                    <td><a href="{{ url_for('request_detail', req_id=r.id) }}" class="btn btn-sm btn-outline-secondary" style="font-size:.7rem">Open</a></td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    {% else %}
                    <div class="text-center py-4" style="color:var(--text-secondary)"><i class="fas fa-inbox fa-2x mb-2"></i><br>No requests yet</div>
                    {% endif %}
                </div>
            </div>
            <div class="col-lg-4">
                <div class="card-premium">
                    <h5 class="mb-3" style="color:var(--rori-gold)"><i class="fas fa-wave-square"></i> Activity Log</h5>
                    {% if recent_activity|length > 0 %}
                    {% for a in recent_activity %}
                    <div style="display:flex;gap:.6rem;padding:.55rem .7rem;background:var(--bg-secondary);border-left:2px solid var(--rori-gold);border-radius:8px;font-size:.78rem;margin-bottom:.4rem">
                        <i class="fas fa-bolt" style="color:var(--rori-gold);margin-top:.15rem"></i>
                        <div style="flex:1">
                            <div style="color:var(--text-primary)"><strong>{{ a.user }}</strong> — {{ a.action }}</div>
                            <div style="font-size:.65rem;color:var(--text-secondary);margin-top:2px">{{ a.time }}</div>
                        </div>
                    </div>
                    {% endfor %}
                    {% else %}
                    <div class="text-center py-4" style="color:var(--text-secondary)"><i class="fas fa-wave-square fa-2x mb-2"></i><br>No activity</div>
                    {% endif %}
                </div>
            </div>
        </div>
    </main>

    <script>
        // Sidebar Toggle
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('show');
        }

        // Audio Alarm Logic
        let audioCtx;
        let isSoundEnabled = localStorage.getItem('rori_sound_enabled') === 'true';
        let alertedRequests = JSON.parse(sessionStorage.getItem('rori_alerted_requests') || '[]');

        function initAudio() {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
            document.getElementById('audioEnableHint').style.display = 'none';
        }

        function playAlarm() {
            if (!isSoundEnabled || !audioCtx) return;
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.frequency.setValueAtTime(880, audioCtx.currentTime);
            osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.15);
            osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.3);
            gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.5);
            osc.start(audioCtx.currentTime);
            osc.stop(audioCtx.currentTime + 0.5);
        }

        function toggleSound(enable) {
            isSoundEnabled = enable;
            localStorage.setItem('rori_sound_enabled', isSoundEnabled);
            if (enable) initAudio();
            updateSoundUI();
        }

        function testSound() {
            initAudio();
            isSoundEnabled = true;
            playAlarm();
            updateSoundUI();
        }

        function updateSoundUI() {
            const btnOn = document.getElementById('soundOn');
            const btnOff = document.getElementById('soundOff');
            if (isSoundEnabled) {
                btnOn.classList.add('btn-warning');
                btnOn.classList.remove('btn-outline-secondary');
                btnOff.classList.remove('btn-warning');
                btnOff.classList.add('btn-outline-secondary');
            } else {
                btnOn.classList.remove('btn-warning');
                btnOn.classList.add('btn-outline-secondary');
                btnOff.classList.add('btn-warning');
                btnOff.classList.remove('btn-outline-secondary');
            }
        }

        function acknowledgeAlert() {
            document.getElementById('newRequestAlert').style.display = 'none';
            document.getElementById('newRequestAlert').classList.remove('alert-pulse');
        }

        async function checkNewRequests() {
            try {
                const response = await fetch('/api/notifications/unread');
                const data = await response.json();
                if (data.latest_title && data.latest_title.includes('NEW MAINTENANCE REQUEST')) {
                    if (!alertedRequests.includes(data.latest_id)) {
                        alertedRequests.push(data.latest_id);
                        sessionStorage.setItem('rori_alerted_requests', JSON.stringify(alertedRequests));
                        
                        const alertBox = document.getElementById('newRequestAlert');
                        if (alertBox) {
                            alertBox.classList.add('alert-pulse');
                            alertBox.style.display = 'block';
                        }
                        
                        const badge = document.querySelector('.notif-badge');
                        if (badge) {
                            badge.textContent = parseInt(badge.textContent || 0) + 1;
                            badge.style.display = 'inline-block';
                        }
                        
                        playAlarm();
                    }
                }
            } catch (e) { console.error('Polling error', e); }
        }

        document.addEventListener('click', initAudio, { once: true });
        updateSoundUI();
        setInterval(checkNewRequests, 10000);

        // Chart.js Configuration
        window.DASHBOARD_DATA = {{ chart_data|tojson }};
        (function(){
            'use strict';
            if(typeof Chart === 'undefined') return;
            var D = window.DASHBOARD_DATA || {};
            Chart.defaults.color = '#A7A7B3';
            Chart.defaults.borderColor = 'rgba(197,160,89,0.1)';
            Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
            var TT = {backgroundColor:'#151522', borderColor:'rgba(197,160,89,0.5)', borderWidth:1, titleColor:'#FFFFFF', bodyColor:'#A7A7B3', padding:11, cornerRadius:10};
            var C = {gold:'#C5A059', green:'#22C55E', blue:'#38BDF8', purple:'#8b5cf6', cyan:'#06b6d4', red:'#EF4444'};

            // 1. Trends Chart
            (function(){
                var el = document.getElementById('chartTrends'); if(!el) return;
                var t = D.trends; if(!t || !t.labels.length) return;
                new Chart(el, {type:'line', data:{labels:t.labels, datasets:[
                    {label:'Total', data:t.total, borderColor:C.gold, borderWidth:2.5, fill:true, backgroundColor:'rgba(197,160,89,0.15)', tension:0.4, pointRadius:0},
                    {label:'Completed', data:t.completed, borderColor:C.green, borderWidth:2.2, fill:true, backgroundColor:'rgba(34,197,94,0.1)', tension:0.4, pointRadius:0},
                    {label:'Pending', data:t.pending, borderColor:C.red, borderWidth:2, tension:0.4, pointRadius:0}
                ]}, options:{responsive:true, maintainAspectRatio:false, interaction:{mode:'index'}, plugins:{legend:{position:'top'}, tooltip:TT}, scales:{x:{grid:{display:false}}, y:{beginAtZero:true, grid:{color:'rgba(197,160,89,0.07)'}}}}});
            })();

            // 2. Status Donut
            (function(){
                var el = document.getElementById('chartStatus'); if(!el) return;
                var s = D.statuses; if(!s || !s.labels.length) return;
                var map = {'Pending':C.gold,'Approved':C.blue,'In Progress':C.purple,'Completed':C.green,'Verified':C.cyan,'Closed':'#16a34a','Rejected':C.red};
                new Chart(el, {type:'doughnut', data:{labels:s.labels, datasets:[{data:s.values, backgroundColor:s.labels.map(l=>map[l]||'#9ca3af'), borderColor:'#11111B', borderWidth:3}]}, options:{responsive:true, maintainAspectRatio:false, cutout:'65%', plugins:{legend:{position:'bottom'}, tooltip:TT}}});
            })();

            // 3. Department Bar
            (function(){
                var el = document.getElementById('chartDept'); if(!el) return;
                var d = D.departments; if(!d || !d.labels.length) return;
                new Chart(el, {type:'bar', data:{labels:d.labels, datasets:[{label:'Requests', data:d.values, backgroundColor:'rgba(197,160,89,0.8)', borderRadius:8}]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT}, scales:{x:{grid:{display:false}}, y:{beginAtZero:true}}}});
            })();

            // 4. Dept Completion
            (function(){
                var el = document.getElementById('chartDeptComp'); if(!el) return;
                var d = D.dept_completion; if(!d || !d.labels.length) return;
                new Chart(el, {type:'bar', data:{labels:d.labels, datasets:[
                    {label:'Total', data:d.totals, backgroundColor:'rgba(167,167,179,0.3)', borderRadius:8},
                    {label:'Completed', data:d.completed, backgroundColor:'rgba(34,197,94,0.8)', borderRadius:8}
                ]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{position:'top'}, tooltip:TT}, scales:{x:{grid:{display:false}}, y:{beginAtZero:true}}}});
            })();
        })();
    </script>
</body>
</html>"""

# ══════════════════════════════════════════ SEED DATA (UNCHANGED)
def seed_data():
    for name in ["Housekeeping","Front Office","Engineering","Food & Beverage","Kitchen","Finance","HR","Security","IT","Sales & Marketing","Administration","Maintenance","Other","SPA","GM"]:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
    db.session.commit()
    for f in [2,3,4,5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))
    if Room.query.count() == 0:
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))
    for n, d in [("Buduchalley","F&B"),("Sillanto","Unknown"),("Fura","Unknown"),("Executive","Unknown"),("Mitima","Unknown"),("Odako","Unknown"),("Gudumale","Unknown"),("Bubble","Unknown"),("Bubbles","Unknown"),("Fura Corridor","Unknown"),("Executive Meeting Room","Unknown"),("Counter","Unknown")]:
        if not Area.query.filter_by(name=n).first(): db.session.add(Area(name=n, department=d))
    for c in ["Electrical","Plumbing","HVAC","Painting","Carpentry","Civil","Safety","General","Other"]:
        if not Category.query.filter_by(name=c).first(): db.session.add(Category(name=c))
    for i in ["Light","Switch","Window","Door Key","Door Lock","Paint","Mirror","Drainage Cover","Frame","Background Frame","Spot Light","Plumbing","AC","Electrical","Other"]:
        if not WorkingItem.query.filter_by(name=i).first(): db.session.add(WorkingItem(name=i))
    for eid, n, t in [(1,"Mechanic 1","General Mechanic"),(2,"Mechanic 2","General Mechanic"),(3,"Mechanic 3","General Mechanic"),(4,"Supervisor 1","Supervisor"),(5,"Amir Awel","Manager")]:
        if not db.session.get(Employee, eid): db.session.add(Employee(id=eid, name=n, job_title=t, department="Engineering"))
    if Supplier.query.count() == 0:
        for s in ["ABC Maintenance Supply","Hawassa Engineering Supply","Rori Hotel Approved Supplier"]:
            db.session.add(Supplier(company_name=s, contact_person="", phone="", status="Active", is_active=True))
    hk = Department.query.filter_by(name="Housekeeping").first()
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        u.set_password("admin123")
        db.session.add(u)
    for s in [
        {"u":"amir","n":"Amir Awel","r":"MANAGER","d":None},
        {"u":"kasahun","n":"Kasahun Girma","r":"MANAGER","d":hk.id if hk else None},
        {"u":"abebayhu","n":"Abebaw","r":"SUPERVISOR","d":None},
        {"u":"tesfahun","n":"Tesfahun","r":"TECHNICIAN","d":None},
        {"u":"simon","n":"Simon","r":"TECHNICIAN","d":None},
        {"u":"chernet","n":"Chernet","r":"TECHNICIAN","d":None},
        {"u":"wale","n":"Wale","r":"TECHNICIAN","d":None},
        {"u":"tsadiku","n":"Tsadiku","r":"TECHNICIAN","d":None},
        {"u":"employee1","n":"Test Employee","r":"EMPLOYEE","d":None},
        {"u":"housekeeping","n":"Kassahun Girma","r":"DEPARTMENT","d":hk.id if hk else None},
    ]:
        ex = User.query.filter_by(username=s["u"]).first()
        if not ex:
            u = User(username=s["u"], full_name=s["n"], role=s["r"], department_id=s["d"]); u.set_password("123456"); db.session.add(u)
        else:
            ex.full_name = s["n"]; ex.role = s["r"]; ex.department_id = s["d"]
    
    dept_map = {
        "it": {"n": "To be configured later", "dept": "IT"},
        "fnb": {"n": "Bahilu Boja", "dept": "Food & Beverage"},
        "security": {"n": "Tariku Bekele", "dept": "Security"},
        "kitchen": {"n": "Biruk Haile", "dept": "Kitchen"},
        "spa": {"n": "Tesfaye Yohanes", "dept": "SPA"},
        "finance": {"n": "Abel Yemane", "dept": "Finance"},
        "gm": {"n": "Muluken Gedafew", "dept": "GM"},
    }
    for uname, info in dept_map.items():
        dept = Department.query.filter_by(name=info["dept"]).first()
        if not dept: continue
        ex = User.query.filter_by(username=uname).first()
        if not ex:
            u = User(username=uname, full_name=info["n"], role="DEPARTMENT", department_id=dept.id, email=uname + "@rorihotel.local")
            u.set_password("123456")
            db.session.add(u)
        else:
            ex.full_name = info["n"]; ex.role = "DEPARTMENT"; ex.department_id = dept.id
    db.session.flush()
    
    sig_configs = [
        {"dept": "IT", "name": "To be configured"},
        {"dept": "Food & Beverage", "name": "Bahilu Boja"},
        {"dept": "Security", "name": "Tariku Bekele"},
        {"dept": "Kitchen", "name": "Biruk Haile"},
        {"dept": "SPA", "name": "Tesfaye Yohanes"},
        {"dept": "Finance", "name": "Abel Yemane"},
        {"dept": "GM", "name": "Muluken Gedafew"},
        {"dept": "Housekeeping", "name": "Kassahun Girma"},
    ]
    for cfg in sig_configs:
        dept = Department.query.filter_by(name=cfg["dept"]).first()
        if not dept: continue
        existing = DepartmentSignature.query.filter_by(department_id=dept.id).first()
        if not existing:
            db.session.add(DepartmentSignature(department_id=dept.id, authorized_name=cfg["name"], is_active=True))
        else:
            existing.authorized_name = cfg["name"]; existing.is_active = True
    db.session.commit()
    print("✅ Seed data loaded")

# ══════════════════════════════════════════ AUTH & ROUTES (UNCHANGED)
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN","MANAGER"]: return redirect(url_for("dashboard"))
        if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
        if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
        return redirect(url_for("workorders_list"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("index"))
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username","").strip()).first()
        if u and u.check_password(request.form.get("password","")) and u.active:
            login_user(u); log_audit("Login","User",u.id); db.session.commit(); return redirect(url_for("index"))
        flash("Incorrect username or password","danger")
    lh = """<div class="d-flex justify-content-center align-items-center" style="min-height:100vh;background:var(--bg-primary)">
<div class="card-premium" style="width:100%;max-width:400px;padding:2rem">
<div class="text-center mb-4"><h3 class="fw-bold" style="color:var(--rori-gold)"><i class="fas fa-hotel"></i> RORI HOTEL</h3><p style="color:var(--text-secondary)">Maintenance Management System</p></div>
<form method="post">
<div class="mb-3"><label class="form-label" style="color:var(--text-secondary)">Username</label><input type="text" class="form-control-dark form-control" name="username" required autofocus></div>
<div class="mb-4"><label class="form-label" style="color:var(--text-secondary)">Password</label><input type="password" class="form-control-dark form-control" name="password" required></div>
<button class="btn w-100" style="background:var(--rori-gold);color:#000;font-weight:600"><i class="fas fa-sign-in-alt"></i> Login</button>
</form>
<hr style="border-color:var(--border-color);margin:1.5rem 0">
<div class="text-center small" style="color:var(--text-secondary)">
<p class="mb-1">Admin: <b style="color:var(--rori-gold)">admin / admin123</b></p>
<p class="mb-0">Manager: <b style="color:var(--rori-gold)">amir / 123456</b></p>
</div>
</div></div>"""
    return render_template_string(DASHBOARD_TEMPLATE.replace('<!-- Main Content -->', '').replace('</main>', '').replace('</body></html>', ''), content=lh)

@app.route("/logout")
@login_required
def logout():
    log_audit("Logout","User",current_user.id); db.session.commit(); logout_user(); return redirect(url_for("login"))

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    u = current_user
    if request.method == "POST":
        u.email = request.form.get("email","").strip(); u.phone = request.form.get("phone","").strip()
        np = request.form.get("new_password","").strip()
        if np: u.set_password(np)
        db.session.commit(); flash("Profile updated","success"); return redirect(url_for("profile"))
    c = ('<div class="card-premium"><h4 style="color:var(--rori-gold);margin-bottom:1rem;">👤 Profile</h4>'
         '<p>@' + str(u.username) + ' · <span class="badge badge-gold">' + str(u.role) + '</span></p>'
         '<p style="color:var(--text-secondary)">📧 ' + str(u.email or "—") + ' | 📱 ' + str(u.phone or "—") + '</p>'
         '<p style="color:var(--text-secondary)">🏢 Department: <strong style="color:var(--text-primary)">' + str(u.department.name if u.department else "Not assigned") + '</strong></p><hr style="border-color:var(--border-color)">'
         '<form method="post"><div class="mb-3"><label class="form-label" style="color:var(--text-secondary)">Email</label><input type="email" class="form-control-dark form-control" name="email" value="' + str(u.email or "") + '"></div>'
         '<div class="mb-3"><label class="form-label" style="color:var(--text-secondary)">Phone</label><input type="text" class="form-control-dark form-control" name="phone" value="' + str(u.phone or "") + '"></div>'
         '<div class="mb-3"><label class="form-label" style="color:var(--text-secondary)">New Password</label><input type="password" class="form-control-dark form-control" name="new_password" placeholder="Leave blank to keep current"></div>'
         '<button class="btn" style="background:var(--rori-gold);color:#000;font-weight:600"><i class="fas fa-save"></i> Save</button></form></div>')
    return page("Profile", c)

# ══════════════════════════════════════════ REQUESTS (UNCHANGED)
@app.route("/requests")
@login_required
def requests_list():
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if current_user.role in ["MANAGER","ADMIN"]: pass
    elif current_user.role == "DEPARTMENT":
        if current_user.department_id: q = q.filter(db.or_(MaintenanceRequest.department_id == current_user.department_id, MaintenanceRequest.requested_by_id == current_user.id))
        else: q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    elif current_user.role == "EMPLOYEE": q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    elif current_user.role in STAFF_ROLES: q = q.filter(MaintenanceRequest.assigned_to_id == current_user.id)
    if request.args.get("status"): q = q.filter(MaintenanceRequest.status == request.args["status"])
    if request.args.get("priority"): q = q.filter(MaintenanceRequest.priority == request.args["priority"])
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    is_mgr = current_user.role in ["MANAGER","ADMIN"]
    rows = []
    for r in reqs:
        del_html = ""
        if is_mgr:
            del_html = ('<form method="post" action="' + url_for("request_delete", req_id=r.id) + '" style="display:inline" onsubmit="return confirm(\'Archive?\');">'
                        '<input type="hidden" name="reason" value="Archived by manager"><button type="submit" class="btn btn-sm btn-outline-danger"><i class="fas fa-archive"></i></button></form>')
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold)">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.working_item.name if r.working_item else "—") + '</td><td>' + str(r.department.name if r.department else "—") + '</td><td><span class="badge badge-gold">' + str(r.priority) + '</span></td><td><span class="badge badge-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td>' + ('<td>' + del_html + '</td>' if is_mgr else '') + '</tr>')
    header = '<thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Created</th>' + ('<th></th>' if is_mgr else '') + '</tr></thead>'
    content = ('<div class="d-flex justify-content-between mb-3"><h3 style="color:var(--rori-gold)"><i class="fas fa-tasks"></i> Maintenance Requests</h3><a href="' + url_for("request_create") + '" class="btn" style="background:var(--rori-gold);color:#000;font-weight:600"><i class="fas fa-plus-circle"></i> New Request</a></div>'
         '<div class="card-premium"><div class="table-responsive"><table class="table table-dark-premium table-hover">' + header + '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="' + ('8' if is_mgr else '7') + '" class="text-center">No requests found</td></tr>') + '</tbody></table></div></div>')
    return page("Requests", content)

@app.route("/requests/new", methods=["GET","POST"])
@login_required
def request_create():
    depts = Department.query.order_by(Department.name).all()
    cats = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()] or sorted({r.floor for r in Room.query.all()})
    sig_profile = get_user_signature_profile(current_user)
    user_dept_name = current_user.department.name if current_user.department else None
    user_dept_id = current_user.department_id
    if request.method == "POST":
        try:
            lt = request.form.get("location_type","Room").strip() or "Room"
            rid = request.form.get("room_id", type=int)
            aid = request.form.get("area_id", type=int)
            wid = request.form.get("working_item_id", type=int)
            cid = request.form.get("category_id", type=int)
            desc = request.form.get("description","").strip()
            prio = request.form.get("priority","MEDIUM")
            fl = request.form.get("floor", type=int)
            did = request.form.get("department_id", type=int)
            if current_user.department_id: did = current_user.department_id
            if current_user.role == "DEPARTMENT" and current_user.department_id: did = current_user.department_id
            if lt == "Room" and rid:
                rm = get_one(Room, rid)
                if rm: fl = rm.floor
            elif lt == "Area": rid = None
            else: rid = None; aid = None
            if not desc:
                flash("Description is required","danger"); return redirect(url_for("request_create"))
            sig_data = request.form.get("signature_data", "").strip()
            sig_name_from_form = request.form.get("signature_name", "").strip()
            ok, err = validate_signature_for_user(current_user, sig_data)
            if not ok:
                flash(err, "danger"); return redirect(url_for("request_create"))
            if sig_profile and sig_name_from_form:
                if sig_name_from_form != sig_profile.authorized_name:
                    flash("Signature name mismatch. You cannot impersonate another department's authorized signature.", "danger"); return redirect(url_for("request_create"))
            authorized_name = sig_profile.authorized_name if sig_profile else (current_user.full_name or current_user.username)
            req = MaintenanceRequest(
                request_no=request_no_generator(), location_type=lt, floor=fl, room_id=rid, area_id=aid,
                working_item_id=wid, category_id=cid, description=desc, priority=prio, status="Pending",
                requested_by_id=current_user.id, department_id=did, awaiting_hk_approval=False,
                signature_name=authorized_name, signature_status="SIGNED", signature_signed_at=datetime.utcnow(),
                signature_data=sig_data, signature_department=user_dept_name, signature_verified=True, signature_user_id=current_user.id,
            )
            req.due_date = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio,24))
            db.session.add(req); db.session.flush()
            log_audit("Create Request","MaintenanceRequest",req.id,new_value=req.request_no)
            log_audit("Digital Signature","MaintenanceRequest",req.id,new_value=authorized_name + " @ " + str(user_dept_name))
            log_status_change(req.id,"Pending",notes="Created and signed by " + str(authorized_name) + " (" + str(user_dept_name) + ")")
            managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"]), User.active == True).all()
            notify_users([u.id for u in managers], req.id, "📝 New Request", "Request " + str(req.request_no) + " from " + str(user_dept_name or "N/A") + " is pending approval", "New Request", link=url_for("request_detail", req_id=req.id))
            db.session.commit()
            flash("✅ Request created successfully with verified digital signature!","success")
            return redirect(url_for("request_detail", req_id=req.id))
        except Exception as e:
            db.session.rollback(); print("Create error: " + traceback.format_exc())
            flash("Error: " + str(e),"danger"); return redirect(url_for("request_create"))
    
    fo = "".join('<option value="' + str(f) + '">Floor ' + str(f) + '</option>' for f in floors)
    ro = "".join('<option value="' + str(r.id) + '">Room ' + str(r.room_number) + ' (F' + str(r.floor) + ')</option>' for r in rooms)
    ao = "".join('<option value="' + str(a.id) + '">' + str(a.name) + '</option>' for a in areas)
    io_ = "".join('<option value="' + str(i.id) + '">' + str(i.name) + '</option>' for i in items)
    co = "".join('<option value="' + str(c.id) + '">' + str(c.name) + '</option>' for c in cats)
    po = "".join('<option value="' + p + '"' + (' selected' if p=="MEDIUM" else '') + '>' + p + '</option>' for p in ["URGENT","HIGH","MEDIUM","LOW"])
    sig_authorized_name = sig_profile.authorized_name if sig_profile else "Not configured"
    sig_dept_display = user_dept_name or "Not assigned"
    sig_warning = "" if sig_profile else '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> No authorized signature configured for your department. Contact admin before submitting requests.</div>'
    sig_configured_class = "border-success" if sig_profile else "border-danger"
    
    content = ('<h3 style="color:var(--rori-gold)"><i class="fas fa-plus-circle"></i> New Maintenance Request</h3>' + sig_warning +
         '<div class="card-premium"><form method="post" id="requestForm"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label" style="color:var(--text-secondary)">Location Type *</label><select class="form-select-dark form-select" name="location_type" id="locationType" required><option value="Room" selected>Room</option><option value="Area">Area</option></select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label" style="color:var(--text-secondary)">Department (Auto-detected)</label><input type="text" class="form-control-dark form-control" value="' + str(sig_dept_display) + '" readonly style="background:rgba(34,197,94,0.1);border-color:#22c55e;color:#22c55e;font-weight:600"><input type="hidden" name="department_id" value="' + str(user_dept_id or "") + '"></div>'
         '<div class="col-md-6 mb-3" id="roomWrap"><label class="form-label" style="color:var(--text-secondary)">Room</label><select class="form-select-dark form-select" name="room_id"><option value="">-- Select Room --</option>' + ro + '</select></div>'
         '<div class="col-md-6 mb-3" id="floorWrap" style="display:none"><label class="form-label" style="color:var(--text-secondary)">Floor</label><select class="form-select-dark form-select" name="floor"><option value="">-- Floor --</option>' + fo + '</select></div>'
         '<div class="col-md-6 mb-3" id="areaWrap" style="display:none"><label class="form-label" style="color:var(--text-secondary)">Area</label><select class="form-select-dark form-select" name="area_id"><option value="">-- Select Area --</option>' + ao + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label" style="color:var(--text-secondary)">Working Item</label><select class="form-select-dark form-select" name="working_item_id"><option value="">-- Select Item --</option>' + io_ + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label" style="color:var(--text-secondary)">Category</label><select class="form-select-dark form-select" name="category_id"><option value="">-- Select Category --</option>' + co + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label" style="color:var(--text-secondary)">Priority *</label><select class="form-select-dark form-select" name="priority">' + po + '</select></div>'
         '<div class="col-12 mb-3"><label class="form-label" style="color:var(--text-secondary)">Description *</label><textarea class="form-control-dark form-control" name="description" rows="4" required placeholder="Describe the issue…"></textarea></div>'
         '<div class="col-12 mb-3"><div class="card-premium ' + sig_configured_class + '" style="background:rgba(34,197,94,0.05);border-width:2px">'
         '<h5 style="color:#22c55e;margin-bottom:1rem"><i class="fas fa-signature"></i> Authorized Digital Signature</h5>'
         '<div class="row g-3">'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-secondary);border-radius:10px"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px">Signed By (Authorized)</div><div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);margin-top:.25rem">' + str(sig_authorized_name) + '</div><input type="hidden" name="signature_name" value="' + str(sig_authorized_name) + '"></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-secondary);border-radius:10px"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px">Department</div><div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);margin-top:.25rem">' + str(sig_dept_display) + '</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:rgba(34,197,94,0.1);border-radius:10px;border:1px solid #22c55e"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px">Signature Status</div><div id="sigStatusText" style="font-size:1rem;font-weight:700;color:var(--warning);margin-top:.25rem"><i class="fas fa-hourglass-half"></i> Awaiting Signature</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-secondary);border-radius:10px"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px">Requester</div><div style="font-size:1rem;font-weight:600;color:var(--text-primary);margin-top:.25rem">' + str(current_user.full_name or current_user.username) + ' (@' + str(current_user.username) + ')</div></div></div>'
         '</div><hr style="border-color:rgba(34,197,94,0.2);margin:1rem 0">'
         '<label class="form-label" style="color:#22c55e;font-weight:600"><i class="fas fa-pen-nib"></i> Draw Your Signature Below *</label>'
         '<div style="border: 2px dashed rgba(245,158,11,0.4); border-radius: 12px; padding: 10px; background: #fff;">'
         '<canvas id="signature-pad" width="400" height="150" style="width: 100%; height: 150px; cursor: crosshair; touch-action: none;"></canvas>'
         '</div>'
         '<div class="mt-2 d-flex gap-2"><button type="button" class="btn btn-sm btn-outline-secondary" id="clear-signature"><i class="fas fa-eraser"></i> Clear</button><span id="sigHint" style="color:var(--text-secondary);font-size:.85rem;margin-left:.5rem">Please draw your signature above</span></div>'
         '<input type="hidden" name="signature_data" id="signature-data">'
         '</div></div>'
         '<div class="col-12 d-flex gap-2"><a href="' + url_for("index") + '" class="btn btn-outline-secondary"><i class="fas fa-times"></i> Cancel</a><button type="submit" class="btn" style="background:var(--rori-gold);color:#000;font-weight:600" id="submitBtn" disabled><i class="fas fa-paper-plane"></i> Submit Request</button></div></div></form></div>'
         '<script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js"></script>'
         '<script>(function(){var canvas = document.getElementById("signature-pad");var signaturePad = new SignaturePad(canvas, { backgroundColor: "rgb(255, 255, 255)", penColor: "rgb(0, 0, 0)" });var submitBtn = document.getElementById("submitBtn");var sigStatusText = document.getElementById("sigStatusText");var sigHint = document.getElementById("sigHint");function resizeCanvas(){var ratio = Math.max(window.devicePixelRatio || 1, 1);canvas.width = canvas.offsetWidth * ratio;canvas.height = canvas.offsetHeight * ratio;canvas.getContext("2d").scale(ratio, ratio);signaturePad.clear();}window.addEventListener("resize", resizeCanvas);resizeCanvas();document.getElementById("clear-signature").addEventListener("click", function(){ signaturePad.clear(); updateSigStatus(); });signaturePad.addEventListener("endStroke", updateSigStatus);function updateSigStatus(){if (signaturePad.isEmpty()){sigStatusText.innerHTML = \'<i class="fas fa-hourglass-half"></i> Awaiting Signature\';sigStatusText.style.color = "#f59e0b";sigHint.textContent = "Please draw your signature above";submitBtn.disabled = true;} else {sigStatusText.innerHTML = \'<i class="fas fa-check-circle"></i> Signature Verified\';sigStatusText.style.color = "#22c55e";sigHint.textContent = "✓ Signature captured - ready to submit";submitBtn.disabled = false;}}document.querySelector("#requestForm").addEventListener("submit", function(e){if (signaturePad.isEmpty()){e.preventDefault();alert("Digital signature is required. Your request cannot be submitted without a verified department signature.");return false;}document.getElementById("signature-data").value = signaturePad.toDataURL("image/png");});})();</script>'
         '<script>(function(){var lt=document.getElementById("locationType");var rw=document.getElementById("roomWrap");var aw=document.getElementById("areaWrap");var fw=document.getElementById("floorWrap");function upd(){var v=lt.value;if(v==="Room"){rw.style.display="";aw.style.display="none";fw.style.display="none";}else{rw.style.display="none";aw.style.display="";fw.style.display="";}}lt.addEventListener("change",upd);upd();})();</script>')
    return page("New Request", content)

# ... [All other existing routes like request_detail, request_approve, request_verify, request_close, request_delete, deleted_requests, request_restore, analytics helpers, department_dashboard, employee_dashboard, workorders, suppliers, inventory, notifications, rooms, areas, employees, admin_users, audit_logs, backup_page, reports, debug, manifest, sw, logo, errors remain EXACTLY as they were in the original app.py to preserve business logic] ...

# ══════════════════════════════════════════ UPDATED DASHBOARD ROUTE
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role in STAFF_ROLES: return redirect(url_for("workorders_list"))
    if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
    
    args = request.args
    kpis = get_kpis(args)
    trends = get_trends(args)
    statuses = get_status_stats(args)
    departments = get_dept_stats(args)
    dept_completion = get_dept_completion(args)
    priorities = get_priority_stats(args)
    categories = get_category_stats(args)
    floors = get_floor_stats(args)
    tech_workload = get_technician_workload(args)
    activity = get_recent_activity(10)
    inventory = get_inventory_summary()
    recent_reqs = build_filtered_query(args).order_by(MaintenanceRequest.created_at.desc()).limit(15).all()
    
    # New variables for premium dashboard
    urgent_count = MaintenanceRequest.query.filter_by(is_deleted=False, priority="URGENT").count()
    total_work_hours = db.session.query(func.sum(WorkOrder.labor_hours)).filter(WorkOrder.status.in_(['Completed', 'Verified', 'Closed'])).scalar() or 0
    active_staff_count = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).count()
    completed_work = WorkOrder.query.filter(WorkOrder.status.in_(['Completed', 'Verified', 'Closed'])).order_by(WorkOrder.completed_date.desc()).limit(5).all()
    
    all_depts = Department.query.order_by(Department.name).all()
    all_cats = Category.query.order_by(Category.name).all()
    all_rooms = Room.query.order_by(Room.room_number).all()
    all_areas = Area.query.order_by(Area.name).all()
    all_floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()]
    if not all_floors: all_floors = sorted({r.floor for r in Room.query.all()})
    all_staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    
    chart_data = {"trends": trends, "statuses": statuses, "departments": departments,
                  "dept_completion": dept_completion, "priorities": priorities,
                  "categories": categories, "floors": floors}
    
    return render_template_string(DASHBOARD_TEMPLATE,
        kpis=kpis, work_orders={"total": WorkOrder.query.count()},
        staff_stats=tech_workload, inventory=inventory,
        recent_activity=activity, recent_requests=recent_reqs,
        all_departments=all_depts, all_categories=all_cats, all_rooms=all_rooms,
        all_areas=all_areas, all_floors=all_floors, all_staff=all_staff,
        chart_data=chart_data, filters={k: v for k, v in args.items()},
        technician_workload=tech_workload, dept_completion=dept_completion,
        current_user=current_user,
        urgent_count=urgent_count,
        total_work_hours=round(float(total_work_hours), 1),
        active_staff_count=active_staff_count,
        completed_work=completed_work
    )

# ══════════════════════════════════════════ INIT
with app.app_context():
    ensure_database_schema()
    seed_data()
    print("🚀 App initialized with Premium Dark Dashboard")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)