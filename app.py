# app.py
import csv, io, json, os, re, sqlite3, uuid, traceback
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text, inspect
from flask import (Flask, abort, flash, get_flashed_messages, jsonify, redirect,
render_template, render_template_string, request, send_file, url_for, Response)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import qrcode

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
REQUEST_STATUSES = ["Pending", "Pending HK Approval", "Approved", "Assigned", "In Progress", "Completed", "Verified", "Closed", "Rejected", "Overdue"]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png","jpg","jpeg","gif","pdf","doc","docx","xls","xlsx","csv"}
STAFF_ROLES = ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]

# ══════════════════════════════════════════ MODELS
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
    
    # Housekeeping Approval Fields
    awaiting_hk_approval = db.Column(db.Boolean, default=False)
    hk_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    hk_approved_at = db.Column(db.DateTime)
    hk_approval_status = db.Column(db.String(20))
    hk_signature_data = db.Column(db.Text)
    hk_approval_notes = db.Column(db.Text)
    
    # Digital Signature Fields
    signature_name = db.Column(db.String(150), nullable=True)
    signature_status = db.Column(db.String(30), default="SIGNED")
    signature_signed_at = db.Column(db.DateTime, nullable=True)

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

# ══════════════════════════════════════════ HELPERS
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

def notify_maintenance_staff(req, wo):
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    if not staff: return 0
    title = "🔧 New Work Order: " + str(wo.work_order_no)
    item_name = req.working_item.name if req.working_item else "N/A"
    dept_name = req.department.name if req.department else "N/A"
    msg = ("Request: " + str(req.request_no) + " | WO: " + str(wo.work_order_no) +
           " | Location: " + str(req.location_name) + " | Item: " + str(item_name) +
           " | Priority: " + str(req.priority) + " | Dept: " + str(dept_name))
    link = url_for("workorder_detail", wo_id=wo.id)
    c = 0
    for s in staff:
        if create_notification(s.id, req.id, title, msg, "Work Order Assigned", link, wo.id): c += 1
    return c

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
            
            # Digital Signature Schema Migration
            add_column_if_missing("maintenance_requests","signature_name","ALTER TABLE maintenance_requests ADD COLUMN signature_name VARCHAR(150)")
            add_column_if_missing("maintenance_requests","signature_status","ALTER TABLE maintenance_requests ADD COLUMN signature_status VARCHAR(30) DEFAULT 'SIGNED'")
            add_column_if_missing("maintenance_requests","signature_signed_at","ALTER TABLE maintenance_requests ADD COLUMN signature_signed_at " + dt)

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

# ══════════════════════════════════════════ PAGE
def page(title, content):
    nav = []
    if current_user.is_authenticated:
        r = current_user.role
        if r == "DEPARTMENT":
            nav = [('<i class="fas fa-home"></i> Dashboard', url_for('department_dashboard')),
                   ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        elif r == "EMPLOYEE":
            nav = [('<i class="fas fa-home"></i> My Dashboard', url_for('employee_dashboard')),
                   ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        elif r in STAFF_ROLES:
            nav = [('<i class="fas fa-tools"></i> My Tasks', url_for('workorders_list')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        else:
            nav = [('<i class="fas fa-home"></i> Dashboard', url_for('dashboard')),
                   ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                   ('<i class="fas fa-tasks"></i> Requests', url_for('requests_list')),
                   ('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')),
                   ('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')),
                   ('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')),
                   ('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')),
                   ('<i class="fas fa-truck"></i> Suppliers', url_for('suppliers_list')),
                   ('<i class="fas fa-users"></i> Employees', url_for('employees_list'))]
            if r == "ADMIN":
                nav += [('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')),
                        ('<i class="fas fa-history"></i> Audit', url_for('audit_logs')),
                        ('<i class="fas fa-trash"></i> Deleted', url_for('deleted_requests')),
                        ('<i class="fas fa-archive"></i> Backup', url_for('backup_page'))]
            nav += [('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')),
                    ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                    ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                    ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
    else:
        nav = [('<i class="fas fa-sign-in-alt"></i> Login', url_for('login'))]
        
    nav_html = "".join('<a class="nav-link" href="' + str(u) + '">' + str(l) + '</a>' for l, u in nav)
    bell_html = ""
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        badge = '<span class="badge bg-danger" style="position:absolute;top:-5px;right:-5px;font-size:0.7rem;">' + str(unread) + '</span>' if unread > 0 else ""
        bell_html = '<a class="nav-link" id="nav-bell" href="' + url_for('notifications') + '" style="position:relative;"><i class="fas fa-bell"></i>' + badge + '</a>'
        
    flash_html = "".join('<div class="alert alert-' + str(c) + ' alert-dismissible fade show">' + str(m) + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>' for c, m in get_flashed_messages(with_categories=True))
    
    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>""" + str(title) + """ | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);min-height:100vh;color:#e2e8f0;padding-top:70px}
.navbar{background:rgba(15,23,42,0.95)!important;backdrop-filter:blur(16px);border-bottom:1px solid rgba(245,158,11,0.25);padding:.75rem 1.5rem}
.navbar-brand{font-weight:800;font-size:1.3rem;color:#f59e0b!important}
.nav-link{color:#cbd5e1!important;padding:.5rem 1rem!important;border-radius:40px;font-size:.9rem}
.nav-link i{color:#f59e0b;margin-right:4px}
.nav-link:hover{background:rgba(245,158,11,0.12);color:#f59e0b!important}
.navbar-toggler{border-color:rgba(245,158,11,0.4)}
.container{max-width:1400px;padding:1.5rem}
.card{background:rgba(30,41,59,0.7);border:1px solid rgba(245,158,11,0.15);border-radius:20px;color:#e2e8f0;padding:1.25rem;margin-bottom:1.5rem}
.metric-card{background:rgba(30,41,59,0.5);border:1px solid rgba(245,158,11,0.12);border-radius:20px;padding:1.2rem 1rem;text-align:center;height:100%}
.metric-value{font-size:2rem;font-weight:700;color:#f8fafc}
.metric-label{font-size:.8rem;color:#94a3b8;text-transform:uppercase}
.table{color:#e2e8f0}
.table thead th{color:#f59e0b;border-bottom:2px solid rgba(245,158,11,0.2);font-size:.75rem;text-transform:uppercase;padding:10px}
.table td{padding:10px;border-color:rgba(245,158,11,0.08)}
.table-hover tbody tr:hover{background-color:rgba(245,158,11,0.06)}
.btn{border-radius:40px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background:linear-gradient(135deg,#f59e0b,#d97706);color:#0f172a}
.btn-success{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}
.btn-warning{background:linear-gradient(135deg,#eab308,#ca8a04);color:#0f172a}
.btn-danger{background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff}
.btn-info{background:linear-gradient(135deg,#06b6d4,#0891b2);color:#fff}
.btn-secondary{background:#475569;color:#fff}
.btn-sm{padding:.4rem .9rem;font-size:.85rem}
.form-control,.form-select{background:rgba(15,23,42,0.6);border:1px solid rgba(245,158,11,0.2);border-radius:12px;color:#e2e8f0;padding:.75rem 1rem}
.form-control:focus,.form-select:focus{background:rgba(15,23,42,0.9);color:#f8fafc;border-color:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,0.15)}
.form-label{color:#cbd5e1;font-weight:500}
.alert{border-radius:16px;border:none;background:rgba(30,41,59,0.7);color:#e2e8f0}
.alert-success{border-left:4px solid #22c55e}.alert-danger{border-left:4px solid #ef4444}
.alert-warning{border-left:4px solid #f59e0b}.alert-info{border-left:4px solid #06b6d4}
.login-card{background:rgba(30,41,59,0.5);backdrop-filter:blur(20px);border:1px solid rgba(245,158,11,0.2);border-radius:32px;padding:2rem 2.5rem;max-width:440px;margin:0 auto}
.badge{padding:.4rem .8rem;border-radius:20px;font-weight:600;font-size:.75rem}
@keyframes bell-pulse{0%{transform:scale(1)}25%{transform:scale(1.35)}50%{transform:scale(1)}75%{transform:scale(1.25)}100%{transform:scale(1)}}
.bell-alert{animation:bell-pulse .6s ease-in-out 3;color:#f59e0b!important}
@media(max-width:768px){.nav-link{padding:.5rem .8rem!important;font-size:.85rem}.metric-value{font-size:1.5rem}.login-card{padding:1.5rem;margin:1rem}}
</style></head><body>
<nav class="navbar navbar-expand-lg fixed-top"><div class="container-fluid">
<a class="navbar-brand" href=""" + (url_for('dashboard') if current_user.is_authenticated else url_for('login')) + """"><i class="fas fa-hotel"></i> Rori Hotel</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">""" + nav_html + bell_html + """</div></div>
</div></nav>
<div class="container mt-4">""" + flash_html + content + """</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){
'use strict';
if (!window.NotifState) window.NotifState = { lastUnread: null, audioCtx: null, armed: false };
function playChime(){try{var C=window.AudioContext||window.webkitAudioContext;if(!C)return;if(!window.NotifState.audioCtx)window.NotifState.audioCtx=new C();var ctx=window.NotifState.audioCtx;if(ctx.state==='suspended')ctx.resume();[880,1108.73,1318.51].forEach(function(f,i){var o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+i*0.15;o.type='sine';o.frequency.value=f;g.gain.setValueAtTime(0.0001,t);g.gain.linearRampToValueAtTime(0.28,t+0.03);g.gain.exponentialRampToValueAtTime(0.0001,t+0.55);o.connect(g);g.connect(ctx.destination);o.start(t);o.stop(t+0.6);});}catch(e){}}
function vibrate(){try{if(navigator.vibrate)navigator.vibrate([250,120,250,120,400]);}catch(e){}}
function flashBell(){var b=document.getElementById('nav-bell');if(!b)return;b.classList.add('bell-alert');setTimeout(function(){b.classList.remove('bell-alert');},2000);}
function flashTitle(n){var o=document.title,c=0,iv=setInterval(function(){document.title=(c%2===0)?('🔔 ('+n+') '+o):o;c++;if(c>6){clearInterval(iv);document.title=o;}},700);}
function poll(){fetch('/api/notifications/unread',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.ok?r.json():null;}).then(function(d){if(!d)return;var p=window.NotifState.lastUnread,c=d.unread;if(p===null){window.NotifState.lastUnread=c;return;}if(c>p){playChime();vibrate();flashBell();flashTitle(c);}window.NotifState.lastUnread=c;}).catch(function(){});}
function arm(){if(window.NotifState.armed)return;try{var C=window.AudioContext||window.webkitAudioContext;if(C){if(!window.NotifState.audioCtx)window.NotifState.audioCtx=new C();if(window.NotifState.audioCtx.state==='suspended')window.NotifState.audioCtx.resume();}window.NotifState.armed=true;}catch(e){}}
document.addEventListener('click',arm);document.addEventListener('touchstart',arm);document.addEventListener('keydown',arm);
if(document.getElementById('nav-bell')){poll();setInterval(poll,15000);}
})();
</script></body></html>"""

# ══════════════════════════════════════════ SEED
def seed_data():
    for name in ["Housekeeping","Front Office","Engineering","Food & Beverage","Kitchen","Finance","HR","Security","IT","Sales & Marketing","Administration","Maintenance","Other"]:
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
        
    for eid, n, t in [(1,"ተስፋሁን ነከረ","General Mechanic"),(2,"ቸርነት አሞና","General Mechanic"),(3,"ስምዖን ዮሐንስ","General Mechanic"),(4,"አበባየሁ ክፍሌ","Supervisor"),(5,"አሚር አወል","Manager")]:
        if not db.session.get(Employee, eid): db.session.add(Employee(id=eid, name=n, job_title=t, department="Engineering"))
        
    if Supplier.query.count() == 0:
        for s in ["ABC Maintenance Supply","Hawassa Engineering Supply","Rori Hotel Approved Supplier"]:
            db.session.add(Supplier(company_name=s, contact_person="", phone="", status="Active", is_active=True))
            
    hk = Department.query.filter_by(name="Housekeeping").first()
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local"); u.set_password("admin123"); db.session.add(u)
        
    for s in [
        {"u":"amir","n":"Amir Awel","r":"MANAGER","d":None},
        {"u":"kasahun","n":"Kasahun Girma","r":"MANAGER","d":hk.id if hk else None},
        {"u":"abebayhu","n":"አበባየሁ ክፍሌ","r":"SUPERVISOR","d":None},
        {"u":"tesfahun","n":"ተስፋሁን ነከረ","r":"TECHNICIAN","d":None},
        {"u":"simon","n":"ስምዖን ዮሐንስ","r":"TECHNICIAN","d":None},
        {"u":"chernet","n":"ቸርነት አሞና","r":"TECHNICIAN","d":None},
        {"u":"wale","n":"ዋሌ","r":"TECHNICIAN","d":None},
        {"u":"tsadiku","n":"ፃዲቁ","r":"TECHNICIAN","d":None},
        {"u":"employee1","n":"Test Employee","r":"EMPLOYEE","d":None},
        {"u":"housekeeping","n":"Housekeeping Staff","r":"DEPARTMENT","d":hk.id if hk else None},
    ]:
        ex = User.query.filter_by(username=s["u"]).first()
        if not ex:
            u = User(username=s["u"], full_name=s["n"], role=s["r"], department_id=s["d"]); u.set_password("123456"); db.session.add(u)
        else:
            ex.full_name = s["n"]; ex.role = s["r"]; ex.department_id = s["d"]
    db.session.commit()
    print("✅ Seed data loaded")

# ══════════════════════════════════════════ AUTH
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
        flash("የተሳሳተ መለያ ስም ወይም የይለፍ ቃል","danger")
        
    lh = """<div class="row justify-content-center align-items-center" style="min-height:80vh">
<div class="col-11 col-md-5"><div class="login-card">
<div class="text-center mb-4"><h3 class="fw-bold" style="color:#f59e0b"><i class="fas fa-hotel"></i> Rori Hotel</h3><p style="color:#94a3b8">የጥገና ክፍል መግቢያ</p></div>
<form method="post"><div class="mb-3"><label class="form-label">መለያ ስም</label><input type="text" class="form-control" name="username" required autofocus></div>
<div class="mb-4"><label class="form-label">የይለፍ ቃል</label><input type="password" class="form-control" name="password" required></div>
<button class="btn btn-primary w-100"><i class="fas fa-sign-in-alt"></i> ግባ</button></form>
<hr class="my-4" style="border-color:rgba(245,158,11,0.2)"><div class="text-center small" style="color:#94a3b8">
<p class="mb-1">Manager (Amir): <b>amir / 123456</b></p>
<p class="mb-1">HK Manager (Kasahun): <b>kasahun / 123456</b></p>
<p class="mb-0">Admin: <b>admin / admin123</b></p></div>
</div></div></div>"""
    return page("Login", lh)

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
        db.session.commit(); flash("መረጃዎ ተዘምኗል","success"); return redirect(url_for("profile"))
        
    c = ('<h3 style="color:#f59e0b">👤 መገለጫ</h3><div class="card"><h4>' + str(u.full_name) + '</h4>'
         '<p>@' + str(u.username) + ' · <span class="badge bg-warning text-dark">' + str(u.role) + '</span></p>'
         '<p>📧 ' + str(u.email or "—") + ' | 📱 ' + str(u.phone or "—") + '</p><hr>'
         '<form method="post"><div class="mb-3"><label class="form-label">ኢሜል</label><input type="email" class="form-control" name="email" value="' + str(u.email or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">ስልክ</label><input type="text" class="form-control" name="phone" value="' + str(u.phone or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">አዲስ የይለፍ ቃል</label><input type="password" class="form-control" name="new_password" placeholder="ባዶ ከሆነ አይለወጥም"></div>'
         '<button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div>')
    return page("Profile", c)

# ══════════════════════════════════════════ REQUESTS
@app.route("/requests")
@login_required
def requests_list():
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if current_user.role in ["MANAGER","ADMIN"]:
        pass
    elif current_user.role == "DEPARTMENT":
        if current_user.department_id:
            q = q.filter(db.or_(MaintenanceRequest.department_id == current_user.department_id,
                                MaintenanceRequest.requested_by_id == current_user.id))
        else:
            q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    elif current_user.role == "EMPLOYEE":
        q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    elif current_user.role in STAFF_ROLES:
        q = q.filter(MaintenanceRequest.assigned_to_id == current_user.id)
        
    if request.args.get("status"): q = q.filter(MaintenanceRequest.status == request.args["status"])
    if request.args.get("priority"): q = q.filter(MaintenanceRequest.priority == request.args["priority"])
    
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    
    def bd(st): return {"Pending":"warning","Pending HK Approval":"warning","Approved":"primary","Assigned":"info","In Progress":"info",
                        "Completed":"success","Verified":"success","Closed":"secondary",
                        "Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
                        
    is_mgr = current_user.role in ["MANAGER","ADMIN"]
    rows = []
    for r in reqs:
        del_html = ""
        if is_mgr:
            del_html = ('<form method="post" action="' + url_for("request_delete", req_id=r.id) + '" style="display:inline" '
                        'onsubmit="return confirm(\'Delete request ' + str(r.request_no) + '?\')">'
                        '<input type="hidden" name="reason" value="Deleted by manager">'
                        '<button type="submit" class="btn btn-sm btn-danger" title="Delete"><i class="fas fa-trash"></i></button></form>')
                        
        sig_badge = '<span class="badge bg-success"><i class="fas fa-check"></i> Signed</span>' if r.signature_status == "SIGNED" else '<span class="badge bg-secondary">Unsigned</span>'
        
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:#f59e0b">' + str(r.request_no) + '</a></td>'
                    '<td>' + str(r.location_name) + '</td>'
                    '<td>' + str(r.working_item.name if r.working_item else "—") + '</td>'
                    '<td>' + str(r.department.name if r.department else "—") + '</td>'
                    '<td>' + str(r.requested_by.full_name if r.requested_by else "—") + '</td>'
                    '<td>' + sig_badge + '</td>'
                    '<td><span class="badge bg-secondary">' + str(r.priority) + '</span></td>'
                    '<td><span class="badge bg-' + bd(r.status) + '">' + str(r.status) + '</span></td>'
                    '<td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td>'
                    + ('<td style="width:60px;text-align:center">' + del_html + '</td>' if is_mgr else '') + '</tr>')
                    
    header = ('<thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Department</th><th>Requested By</th><th>Signature</th><th>Priority</th><th>Status</th><th>Created</th>'
              + ('<th></th>' if is_mgr else '') + '</tr></thead>')
              
    c = ('<div class="d-flex justify-content-between mb-3"><h3 style="color:#f59e0b"><i class="fas fa-tasks"></i> Maintenance Requests</h3>'
         '<a href="' + url_for("request_create") + '" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a></div>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">' + header +
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="' + ('10' if is_mgr else '9') + '" class="text-center">No requests found</td></tr>') +
         '</tbody></table></div></div>')
    return page("Requests", c)

@app.route("/requests/new", methods=["GET","POST"])
@login_required
def request_create():
    depts = Department.query.order_by(Department.name).all()
    cats = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()] or sorted({r.floor for r in Room.query.all()})
    
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
            
            if current_user.role == "DEPARTMENT" and current_user.department_id: did = current_user.department_id
            if current_user.role == "EMPLOYEE" and not did and current_user.department_id: did = current_user.department_id
            
            if lt == "Room" and rid:
                rm = get_one(Room, rid)
                if rm: fl = rm.floor
            elif lt == "Area": rid = None
            else: rid = None; aid = None
            
            if not desc:
                flash("Description is required","danger"); return redirect(url_for("request_create"))
                
            req = MaintenanceRequest(
                request_no=request_no_generator(), location_type=lt, floor=fl, room_id=rid, area_id=aid,
                working_item_id=wid, category_id=cid, description=desc, priority=prio, status="Pending",
                requested_by_id=current_user.id, department_id=did, awaiting_hk_approval=False,
                signature_name=current_user.full_name,
                signature_status="SIGNED",
                signature_signed_at=datetime.utcnow()
            )
            
            # Housekeeping Workflow Trigger
            if current_user.department and current_user.department.name == "Housekeeping":
                req.awaiting_hk_approval = True
                req.status = "Pending HK Approval"
                
            req.due_date = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio,24))
            db.session.add(req); db.session.flush()
            
            log_audit("REQUEST_CREATED","MaintenanceRequest",req.id,new_value=req.request_no)
            log_audit("DIGITALLY_SIGNED","MaintenanceRequest",req.id,new_value=current_user.full_name)
            log_status_change(req.id, req.status, notes="Created and signed by " + str(current_user.full_name))
            
            managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"]), User.active == True).all()
            notify_users([u.id for u in managers], req.id, "📝 New Request",
                         "Request " + str(req.request_no) + " from " + str(req.department.name if req.department else "N/A") + " is pending",
                         "New Request", link=url_for("request_detail", req_id=req.id))
                         
            db.session.commit()
            flash("✅ Request created successfully! " + req.request_no,"success")
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
    
    show_d = current_user.role not in ["DEPARTMENT"] and not (current_user.role=="EMPLOYEE" and current_user.department_id)
    dhtml = ""
    if show_d:
        dopt = "".join('<option value="' + str(d.id) + '">' + str(d.name) + '</option>' for d in depts)
        dhtml = ('<div class="col-md-6 mb-3"><label class="form-label">Department</label>'
                 '<select class="form-select" name="department_id"><option value="">-- Select --</option>' + dopt + '</select></div>')
                 
    c = ('<h3 style="color:#f59e0b"><i class="fas fa-plus-circle"></i> New Maintenance Request</h3>'
         '<div class="card"><form method="post"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Location Type *</label>'
         '<select class="form-select" name="location_type" id="locationType" required><option value="Room" selected>Room</option><option value="Area">Area</option></select></div>'
         + dhtml +
         '<div class="col-md-6 mb-3" id="roomWrap"><label class="form-label">Room</label>'
         '<select class="form-select" name="room_id"><option value="">-- Select Room --</option>' + ro + '</select></div>'
         '<div class="col-md-6 mb-3" id="floorWrap" style="display:none"><label class="form-label">Floor</label>'
         '<select class="form-select" name="floor"><option value="">-- Floor --</option>' + fo + '</select></div>'
         '<div class="col-md-6 mb-3" id="areaWrap" style="display:none"><label class="form-label">Area</label>'
         '<select class="form-select" name="area_id"><option value="">-- Select Area --</option>' + ao + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Working Item</label>'
         '<select class="form-select" name="working_item_id"><option value="">-- Select Item --</option>' + io_ + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Category</label>'
         '<select class="form-select" name="category_id"><option value="">-- Select Category --</option>' + co + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Priority *</label>'
         '<select class="form-select" name="priority">' + po + '</select></div>'
         '<div class="col-12 mb-3"><label class="form-label">Description *</label>'
         '<textarea class="form-control" name="description" rows="4" required placeholder="Describe the issue…"></textarea></div>'
         '<div class="col-12 d-flex gap-2">'
         '<a href="' + url_for("index") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
         '<button type="submit" class="btn btn-primary"><i class="fas fa-paper-plane"></i> Submit & Sign Request</button>'
         '</div></div></form></div>'
         '<script>(function(){var lt=document.getElementById("locationType");'
         'var rw=document.getElementById("roomWrap");var aw=document.getElementById("areaWrap");var fw=document.getElementById("floorWrap");'
         'function upd(){var v=lt.value;if(v==="Room"){rw.style.display="";aw.style.display="none";fw.style.display="none";}'
         'else{rw.style.display="none";aw.style.display="";fw.style.display="";}}lt.addEventListener("change",upd);upd();})();</script>')
    return page("New Request", c)

@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = get_or_404(MaintenanceRequest, req_id)
    if req.is_deleted and current_user.role != "ADMIN":
        flash("This request has been archived.","warning"); return redirect(url_for("requests_list"))
        
    if current_user.role == "DEPARTMENT":
        same = (current_user.department_id and req.department_id == current_user.department_id)
        if not same and req.requested_by_id != current_user.id: abort(403)
    if current_user.role == "EMPLOYEE" and req.requested_by_id != current_user.id: abort(403)
    
    hist = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.asc()).all()
    wos = WorkOrder.query.filter_by(request_id=req.id).all()
    
    def bd(st): return {"Pending":"warning","Pending HK Approval":"warning","Approved":"primary","Assigned":"info","In Progress":"info",
                        "Completed":"success","Verified":"success","Closed":"secondary",
                        "Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
                        
    hist_html = ""
    for h in hist:
        who = h.user.full_name if h.user else "System"
        when = h.timestamp.strftime("%Y-%m-%d %H:%M") if h.timestamp else ""
        note = (" — " + str(h.notes)) if h.notes else ""
        hist_html += ('<div style="padding:.5rem .75rem;border-left:3px solid #f59e0b;background:rgba(30,41,59,0.5);border-radius:10px;margin-bottom:.4rem">'
                      '<strong style="color:#f59e0b">' + str(h.status) + '</strong> '
                      '<span style="color:#94a3b8;font-size:.85rem">by ' + str(who) + ' · ' + str(when) + note + '</span></div>')
    if not hist_html: hist_html = '<p style="color:#94a3b8">No status history yet.</p>'
    
    wo_html = ""
    for wo in wos:
        wo_html += ('<div style="padding:.5rem .75rem;background:rgba(30,41,59,0.5);border-radius:10px;margin-bottom:.4rem">'
                    '<a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:#f59e0b;font-weight:600">' + str(wo.work_order_no) + '</a> '
                    '<span class="badge bg-info">' + str(wo.status) + '</span> '
                    '<span style="color:#94a3b8;font-size:.85rem">· ' + str(wo.assigned_to.full_name if wo.assigned_to else "Unassigned") + '</span></div>')
    if not wo_html: wo_html = '<p style="color:#94a3b8">No work orders yet.</p>'
    
    # Digital Signature Card
    sig_html = ""
    if req.signature_status == "SIGNED":
        sig_time = req.signature_signed_at.strftime("%d %b %Y, %I:%M %p") if req.signature_signed_at else "N/A"
        sig_html = ('<div class="card" style="border: 1px solid rgba(34, 197, 94, 0.3); background: rgba(34, 197, 94, 0.05); margin-top:1rem;">'
                    '<h6 style="color:#22c55e; margin-bottom:1rem;"><i class="fas fa-signature"></i> DIGITAL SIGNATURE</h6>'
                    '<div style="font-size:1.1rem; font-weight:600; color:#f8fafc; margin-bottom:0.5rem;">' + str(req.signature_name or "Unknown") + '</div>'
                    '<div style="border-bottom: 1px dashed rgba(245,158,11,0.3); margin-bottom:0.75rem;"></div>'
                    '<div style="color:#22c55e; font-weight:600; margin-bottom:0.25rem;"><i class="fas fa-check-circle"></i> Digitally Signed</div>'
                    '<div style="color:#94a3b8; font-size:0.85rem;">Department: ' + str(req.department.name if req.department else "N/A") + '</div>'
                    '<div style="color:#94a3b8; font-size:0.85rem;">Signed: ' + sig_time + '</div>'
                    '</div>')
                    
    actions = []
    is_mgr = current_user.role in ["ADMIN","MANAGER"]
    
    if is_mgr:
        if req.status == "Pending HK Approval":
            actions.append('<form method="post" action="' + url_for("request_hk_approve", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-success"><i class="fas fa-check"></i> HK Approve</button></form>')
            
        if req.status in ["Pending","Pending HK Approval","Approved","Assigned"] and req.assigned_to_id is None:
            actions.append('<a href="' + url_for("workorder_create", request_id=req.id) + '" class="btn btn-primary"><i class="fas fa-user-plus"></i> Assign Staff</a>')
        elif req.status in ["Approved","Assigned"]:
            actions.append('<a href="' + url_for("workorder_create", request_id=req.id) + '" class="btn btn-primary"><i class="fas fa-user-edit"></i> Reassign</a>')
            
        if req.status == "Pending":
            actions.append('<form method="post" action="' + url_for("request_approve", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-success"><i class="fas fa-check"></i> Approve</button></form>')
        if req.status == "Completed":
            actions.append('<form method="post" action="' + url_for("request_verify", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-info"><i class="fas fa-check-double"></i> Verify</button></form>')
        if req.status == "Verified":
            actions.append('<form method="post" action="' + url_for("request_close", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-secondary"><i class="fas fa-lock"></i> Close</button></form>')
        if not req.is_deleted:
            actions.append('<form method="post" action="' + url_for("request_delete", req_id=req.id) + '" style="display:inline" onsubmit="return confirm(\'Delete this request?\')"><input type="hidden" name="reason" value="Deleted by manager"><button type="submit" class="btn btn-danger"><i class="fas fa-trash"></i> Delete</button></form>')
            
    actions_html = " ".join(actions) if actions else ""
    
    c = ('<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">'
         '<h3 style="color:#f59e0b;margin:0"><i class="fas fa-clipboard-list"></i> ' + str(req.request_no) + '</h3>'
         + ('<div>' + actions_html + '</div>' if actions_html else '') + '</div>'
         '<div class="row"><div class="col-md-8"><div class="card"><h5 style="color:#f59e0b">Request Details</h5>'
         '<table class="table"><tbody>'
         '<tr><th style="width:180px;color:#94a3b8">Status</th><td><span class="badge bg-' + bd(req.status) + '">' + str(req.status) + '</span></td></tr>'
         '<tr><th style="color:#94a3b8">Priority</th><td>' + str(req.priority) + '</td></tr>'
         '<tr><th style="color:#94a3b8">Department</th><td>' + str(req.department.name if req.department else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Location</th><td>' + str(req.location_name) + '</td></tr>'
         '<tr><th style="color:#94a3b8">Item</th><td>' + str(req.working_item.name if req.working_item else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Category</th><td>' + str(req.category.name if req.category else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Requested By</th><td><strong>' + str(req.requested_by.full_name if req.requested_by else "—") + '</strong></td></tr>'
         '<tr><th style="color:#94a3b8">Assigned To</th><td>' + str(req.assigned_to.full_name if req.assigned_to else "Not Assigned") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Description</th><td>' + str(req.description or "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Due Date</th><td>' + (req.due_date.strftime("%Y-%m-%d %H:%M") if req.due_date else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Completed</th><td>' + (req.completed_date.strftime("%Y-%m-%d %H:%M") if req.completed_date else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Completion Note</th><td>' + str(req.completion_note or "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Created</th><td>' + (req.created_at.strftime("%Y-%m-%d %H:%M") if req.created_at else "—") + '</td></tr>'
         '</tbody></table>' + sig_html + '</div>'
         '<div class="card"><h5 style="color:#f59e0b"><i class="fas fa-clipboard-list"></i> Work Orders</h5>' + wo_html + '</div>'
         '</div><div class="col-md-4"><div class="card"><h5 style="color:#f59e0b"><i class="fas fa-history"></i> Status History</h5>' + hist_html + '</div></div></div>')
    return page("Request " + str(req.request_no), c)

@app.route("/requests/<int:req_id>/hk-approve", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_hk_approve(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Pending HK Approval":
            flash("Not awaiting HK approval","warning"); return redirect(url_for("request_detail", req_id=req_id))
            
        req.status = "Approved"
        req.awaiting_hk_approval = False
        req.hk_approved_by_id = current_user.id
        req.hk_approved_at = datetime.utcnow()
        req.hk_approval_status = "Approved"
        
        log_status_change(req.id,"Approved",notes="HK Approved by " + str(current_user.full_name))
        log_audit("HK_APPROVE","MaintenanceRequest",req.id,old_value="Pending HK Approval",new_value="Approved")
        
        notify_users([req.requested_by_id], req.id, "✅ HK Approved",
                     "Request " + str(req.request_no) + " approved by Housekeeping", "Approved",
                     link=url_for("request_detail", req_id=req.id))
                     
        db.session.commit(); flash("✅ Housekeeping Approval Granted!","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/approve", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_approve(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Pending":
            flash("Not pending","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Approved"; req.manager_id = current_user.id
        log_status_change(req.id,"Approved",notes="Approved by " + str(current_user.full_name))
        log_audit("Approve","MaintenanceRequest",req.id,"Pending","Approved")
        notify_users([req.requested_by_id], req.id, "Request Approved",
                     "Your request " + str(req.request_no) + " has been approved",
                     "Approved", link=url_for("request_detail", req_id=req.id))
        db.session.commit(); flash("✅ Request approved!","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/verify", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_verify(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Completed":
            flash("Only completed can be verified","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Verified"; req.manager_id = current_user.id
        if not req.completed_date: req.completed_date = datetime.utcnow()
        wo = WorkOrder.query.filter_by(request_id=req.id).first()
        if wo:
            wo.status = "Verified"; wo.verified_by_id = current_user.id; wo.verified_date = datetime.utcnow()
        log_status_change(req.id,"Verified",notes="Verified by " + str(current_user.full_name))
        log_audit("Verify","MaintenanceRequest",req.id,"Completed","Verified")
        notify_users([req.requested_by_id], req.id, "✅ Work Verified",
                     "Request " + str(req.request_no) + " verified", "Verified",
                     link=url_for("request_detail", req_id=req.id))
        db.session.commit(); flash("✅ Work verified!","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/close", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_close(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Verified":
            flash("Only verified can be closed","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Closed"
        log_status_change(req.id,"Closed",notes="Closed by " + str(current_user.full_name))
        log_audit("Close","MaintenanceRequest",req.id,"Verified","Closed")
        notify_users([req.requested_by_id], req.id, "Request Closed",
                     "Request " + str(req.request_no) + " closed", "Closed")
        db.session.commit(); flash("Request closed","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/delete", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_delete(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.is_deleted: flash("Already deleted","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.is_deleted = True; req.deleted_at = datetime.utcnow(); req.deleted_by_id = current_user.id
        req.deletion_reason = request.form.get("reason","Deleted by manager")
        log_audit("SoftDelete","MaintenanceRequest",req.id,"active","deleted",new_value=req.deletion_reason)
        db.session.commit(); flash("Request archived","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("requests_list"))

@app.route("/admin/deleted")
@role_required("ADMIN")
def deleted_requests():
    ds = MaintenanceRequest.query.filter_by(is_deleted=True).order_by(MaintenanceRequest.deleted_at.desc()).all()
    rows = []
    for r in ds:
        rows.append('<tr><td>' + str(r.request_no) + '</td><td>' + str(r.location_name) + '</td>'
                    '<td>' + str(r.status) + '</td>'
                    '<td>' + (r.deleted_at.strftime("%Y-%m-%d %H:%M") if r.deleted_at else "") + '</td>'
                    '<td>' + str(r.deleted_by.full_name if r.deleted_by else "—") + '</td>'
                    '<td>' + str(r.deletion_reason or "—") + '</td>'
                    '<td><form method="post" action="' + url_for("request_restore", req_id=r.id) + '"><button type="submit" class="btn btn-sm btn-success"><i class="fas fa-undo"></i> Restore</button></form></td></tr>')
    c = ('<h3 style="color:#f59e0b">🗑️ Archived Requests</h3><div class="card"><div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>Request #</th><th>Location</th><th>Status</th><th>Deleted At</th><th>Deleted By</th><th>Reason</th><th></th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" class="text-center">No archived requests</td></tr>') + '</tbody></table></div></div>')
    return page("Archived", c)

@app.route("/admin/restore/<int:req_id>", methods=["POST"])
@role_required("ADMIN")
def request_restore(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        req.is_deleted = False; req.deleted_at = None; req.deleted_by_id = None; req.deletion_reason = None
        log_audit("Restore","MaintenanceRequest",req.id,"deleted","active")
        db.session.commit(); flash("Request restored","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("deleted_requests"))

# ══════════════════════════════════════════ ANALYTICS
COMPLETED_STATES = ["Completed","Verified","Closed"]
PENDING_STATES = ["Pending","Pending HK Approval","Approved"]
INPROGRESS_STATES = ["Assigned","In Progress"]

def _parse_date(v):
    if not v: return None
    try: return datetime.strptime(v,"%Y-%m-%d")
    except (ValueError, TypeError): return None

def build_filtered_query(args):
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    d_from = _parse_date(args.get("date_from"))
    if d_from: q = q.filter(MaintenanceRequest.created_at >= d_from)
    d_to = _parse_date(args.get("date_to"))
    if d_to: q = q.filter(MaintenanceRequest.created_at < d_to + timedelta(days=1))
    if args.get("department"):
        try: q = q.filter(MaintenanceRequest.department_id == int(args["department"]))
        except (ValueError, TypeError): pass
    if args.get("category"):
        try: q = q.filter(MaintenanceRequest.category_id == int(args["category"]))
        except (ValueError, TypeError): pass
    if args.get("status"): q = q.filter(MaintenanceRequest.status == args["status"])
    if args.get("floor"):
        try: q = q.filter(MaintenanceRequest.floor == int(args["floor"]))
        except (ValueError, TypeError): pass
    if args.get("room_id"):
        try: q = q.filter(MaintenanceRequest.room_id == int(args["room_id"]))
        except (ValueError, TypeError): pass
    if args.get("area_id"):
        try: q = q.filter(MaintenanceRequest.area_id == int(args["area_id"]))
        except (ValueError, TypeError): pass
    return q

def format_duration(s):
    if s is None: return "N/A"
    if s < 60: return f"{int(s)}s"
    if s < 3600: return f"{int(s/60)}m"
    if s < 86400: return f"{s/3600:.1f} hrs"
    d = int(s // 86400); h = int((s % 86400) // 3600)
    return f"{d}d {h}h" if h else f"{d}d"

def _avg_sec(reqs):
    comp = [r for r in reqs if r.completed_date and r.created_at]
    if not comp: return None
    return sum((r.completed_date - r.created_at).total_seconds() for r in comp) / len(comp)

def get_kpis(args):
    reqs = build_filtered_query(args).all()
    total = len(reqs)
    pending = sum(1 for r in reqs if r.status in PENDING_STATES)
    completed = sum(1 for r in reqs if r.status in COMPLETED_STATES)
    avg = _avg_sec([r for r in reqs if r.status in COMPLETED_STATES])
    rate = (completed / total * 100) if total else 0.0
    return {"total": total, "pending": pending, "completed": completed,
            "completion_rate": round(rate,1), "avg_resolution": format_duration(avg)}

def get_trends(args):
    reqs = build_filtered_query(args).all()
    d_from = _parse_date(args.get("date_from"))
    d_to = _parse_date(args.get("date_to"))
    if d_from and d_to: start, end = d_from, d_to
    else:
        dates = [r.created_at for r in reqs if r.created_at]
        if not dates: return {"labels":[],"total":[],"completed":[],"pending":[],"in_progress":[]}
        start = min(dates).replace(hour=0,minute=0,second=0,microsecond=0)
        end = max(dates).replace(hour=0,minute=0,second=0,microsecond=0)
    span = (end-start).days + 1
    gran = "day" if span <= 31 else "week" if span <= 180 else "month"
    keys, labels = [], []
    if gran == "day":
        cur = start
        while cur <= end:
            keys.append(cur.strftime("%Y-%m-%d")); labels.append(cur.strftime("%b %d")); cur += timedelta(days=1)
    elif gran == "week":
        cur = start - timedelta(days=start.weekday())
        while cur <= end:
            keys.append(cur.strftime("%Y-%m-%d")); labels.append("Wk " + cur.strftime("%b %d")); cur += timedelta(days=7)
    else:
        cur = start.replace(day=1)
        while cur <= end:
            keys.append(cur.strftime("%Y-%m")); labels.append(cur.strftime("%b %Y"))
            cur = cur.replace(year=cur.year+1,month=1) if cur.month == 12 else cur.replace(month=cur.month+1)
    counts = {k:{"total":0,"completed":0,"pending":0,"in_progress":0} for k in keys}
    for r in reqs:
        if not r.created_at: continue
        if gran == "day": k = r.created_at.strftime("%Y-%m-%d")
        elif gran == "week":
            m = r.created_at - timedelta(days=r.created_at.weekday()); k = m.strftime("%Y-%m-%d")
        else: k = r.created_at.strftime("%Y-%m")
        if k in counts:
            counts[k]["total"] += 1
            if r.status in COMPLETED_STATES: counts[k]["completed"] += 1
            elif r.status in PENDING_STATES: counts[k]["pending"] += 1
            elif r.status in INPROGRESS_STATES: counts[k]["in_progress"] += 1
    return {"labels": labels,
            "total": [counts[k]["total"] for k in keys],
            "completed": [counts[k]["completed"] for k in keys],
            "pending": [counts[k]["pending"] for k in keys],
            "in_progress": [counts[k]["in_progress"] for k in keys],
            "granularity": gran}

def get_status_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.status] += 1
    order = ["Pending","Pending HK Approval","Approved","Assigned","In Progress","Completed","Verified","Closed","Rejected","Overdue"]
    total = sum(counts.values())
    items = [(s, counts[s]) for s in order if counts.get(s,0) > 0]
    for s, c in counts.items():
        if s not in order and c > 0: items.append((s, c))
    return {"labels": [k for k,_ in items], "values": [v for _,v in items],
            "percentages": [round(v/total*100,1) if total else 0 for _,v in items],
            "total": total}

def get_dept_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.department.name if r.department else "Unspecified"] += 1
    items = sorted(counts.items(), key=lambda x: -x[1])
    total = sum(counts.values())
    return {"labels": [k for k,_ in items], "values": [v for _,v in items],
            "percentages": [round(v/total*100,1) if total else 0 for _,v in items],
            "total": total}

def get_dept_completion(args):
    reqs = build_filtered_query(args).all()
    depts = {}
    for r in reqs:
        name = r.department.name if r.department else "Unspecified"
        if name not in depts: depts[name] = {"total": 0, "completed": 0}
        depts[name]["total"] += 1
        if r.status in COMPLETED_STATES: depts[name]["completed"] += 1
    items = sorted(depts.items(), key=lambda x: -x[1]["total"])
    return {"labels": [k for k,_ in items],
            "totals": [v["total"] for _,v in items],
            "completed": [v["completed"] for _,v in items],
            "percentages": [round(v["completed"]/v["total"]*100,1) if v["total"] else 0 for _,v in items]}

def get_priority_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.priority or "MEDIUM"] += 1
    order = ["URGENT","HIGH","MEDIUM","LOW"]
    total = sum(counts.values())
    items = [(p, counts[p]) for p in order if counts.get(p,0) > 0]
    return {"labels": [k for k,_ in items], "values": [v for _,v in items],
            "percentages": [round(v/total*100,1) if total else 0 for _,v in items]}

def get_category_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.category.name if r.category else "Uncategorized"] += 1
    items = sorted(counts.items(), key=lambda x: -x[1])
    total = sum(counts.values())
    return {"labels": [k for k,_ in items], "values": [v for _,v in items],
            "percentages": [round(v/total*100,1) if total else 0 for _,v in items]}

def get_floor_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs:
        if r.floor: counts[r.floor] += 1
    items = sorted(counts.items())
    return {"labels": ["Floor " + str(k) for k,_ in items], "values": [v for _,v in items]}

def get_technician_workload(args):
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    d_from = _parse_date(args.get("date_from"))
    d_to = _parse_date(args.get("date_to"))
    result = []
    for s in staff:
        q = WorkOrder.query.filter_by(assigned_to_id=s.id)
        if d_from: q = q.filter(WorkOrder.created_at >= d_from)
        if d_to: q = q.filter(WorkOrder.created_at < d_to + timedelta(days=1))
        wos = q.all()
        comp = [w for w in wos if w.status in COMPLETED_STATES and w.completed_date and w.created_at]
        avg = None
        if comp:
            avg = sum((w.completed_date - w.created_at).total_seconds() for w in comp) / len(comp)
        result.append({
            "name": s.full_name or s.username, "role": s.role,
            "assigned": len(wos),
            "in_progress": sum(1 for w in wos if w.status == "In Progress"),
            "completed": sum(1 for w in wos if w.status in COMPLETED_STATES),
            "avg_resolution": format_duration(avg),
        })
    result.sort(key=lambda x: -x["assigned"])
    return result[:15]

def get_recent_activity(limit=10):
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"user": l.user.full_name if l.user else "System", "action": l.action or "",
             "object_type": l.object_type or "", "object_id": l.object_id or "",
             "time": l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else ""} for l in logs]

def get_inventory_summary():
    parts = InventoryPart.query.filter_by(status="Active").all()
    total = len(parts)
    low = sum(1 for p in parts if 0 < (p.quantity or 0) <= (p.minimum_stock or 0))
    out = sum(1 for p in parts if (p.quantity or 0) <= 0)
    val = sum((p.quantity or 0) * (p.unit_cost or 0) for p in parts)
    return {"total_parts": total, "low_stock": low, "out_of_stock": out, "total_value": round(val,2)}

# ══════════════════════════════════════════ DASHBOARD
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
    all_depts = Department.query.order_by(Department.name).all()
    all_cats = Category.query.order_by(Category.name).all()
    all_rooms = Room.query.order_by(Room.room_number).all()
    all_areas = Area.query.order_by(Area.name).all()
    all_floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()]
    if not all_floors: all_floors = sorted({r.floor for r in Room.query.all()})
    chart_data = {"trends": trends, "statuses": statuses, "departments": departments,
                  "dept_completion": dept_completion, "priorities": priorities,
                  "categories": categories, "floors": floors}
    return render_template_string(DASHBOARD_TEMPLATE,
                                  kpis=kpis, work_orders={"total": WorkOrder.query.count()},
                                  top_locations=[], staff_stats=tech_workload, inventory=inventory,
                                  recent_activity=activity, recent_requests=recent_reqs,
                                  all_departments=all_depts, all_categories=all_cats, all_rooms=all_rooms,
                                  all_areas=all_areas, all_floors=all_floors,
                                  chart_data=chart_data, filters={k: v for k, v in args.items()},
                                  technician_workload=tech_workload, dept_completion=dept_completion,
                                  current_user=current_user)

# ══════════════════════════════════════════ DASHBOARD TEMPLATE
DASHBOARD_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manager Dashboard | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);min-height:100vh;color:#e2e8f0;padding-top:70px}
.navbar{background:rgba(15,23,42,0.95)!important;backdrop-filter:blur(16px);border-bottom:1px solid rgba(245,158,11,0.25);padding:.75rem 1.5rem}
.navbar-brand{font-weight:800;font-size:1.3rem;color:#f59e0b!important}
.nav-link{color:#cbd5e1!important;padding:.5rem 1rem!important;border-radius:40px;font-size:.9rem}
.nav-link i{color:#f59e0b;margin-right:4px}
.nav-link:hover{background:rgba(245,158,11,0.12);color:#f59e0b!important}
.navbar-toggler{border-color:rgba(245,158,11,0.4)}
.container{max-width:1400px;padding:1.5rem}
.card{background:rgba(30,41,59,0.7);border:1px solid rgba(245,158,11,0.15);border-radius:20px;color:#e2e8f0;padding:1.25rem;margin-bottom:1.5rem}
.card h5{color:#f59e0b;font-weight:600}
.metric-card{background:rgba(30,41,59,0.55);border:1px solid rgba(245,158,11,0.12);border-radius:20px;padding:1.2rem 1rem;text-align:center;height:100%;transition:transform .15s}
.metric-card:hover{transform:translateY(-2px);border-color:rgba(245,158,11,0.3)}
.metric-value{font-size:2rem;font-weight:800;color:#f8fafc;line-height:1}
.metric-label{font-size:.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.6px;margin-top:.35rem}
.metric-icon{font-size:1.4rem;color:#f59e0b;margin-bottom:.35rem}
.table{color:#e2e8f0}
.table thead th{color:#f59e0b;border-bottom:2px solid rgba(245,158,11,0.2);font-size:.72rem;text-transform:uppercase;padding:10px;white-space:nowrap}
.table td{padding:10px;border-color:rgba(245,158,11,0.08);font-size:.85rem}
.table-hover tbody tr:hover{background-color:rgba(245,158,11,0.06)}
.btn{border-radius:40px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background:linear-gradient(135deg,#f59e0b,#d97706);color:#0f172a}
.btn-sm{padding:.35rem .8rem;font-size:.78rem}
.form-control,.form-select{background:rgba(15,23,42,0.6);border:1px solid rgba(245,158,11,0.2);border-radius:12px;color:#e2e8f0;padding:.65rem .9rem}
.form-control:focus,.form-select:focus{background:rgba(15,23,42,0.9);color:#f8fafc;border-color:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,0.15)}
.form-label{color:#cbd5e1;font-weight:500;font-size:.82rem}
.badge{padding:.35rem .75rem;border-radius:20px;font-weight:600;font-size:.72rem}
.chart-box{position:relative;width:100%;height:280px}
.chart-box.tall{height:340px}
.chart-box.donut{height:240px}
.prog-list{display:flex;flex-direction:column;gap:.7rem}
.prog-row{display:flex;flex-direction:column;gap:.3rem}
.prog-top{display:flex;justify-content:space-between;font-size:.78rem}
.prog-top .nm{color:#e5e7eb;font-weight:600}
.prog-top .ct{color:#f59e0b;font-weight:800}
.prog-bar{height:6px;background:rgba(245,158,11,0.1);border-radius:6px;overflow:hidden}
.prog-bar span{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#f59e0b,#ec4899)}
.feed{display:flex;flex-direction:column;gap:.4rem}
.feed-item{display:flex;gap:.6rem;padding:.55rem .7rem;background:rgba(15,23,42,0.4);border-left:2px solid #f59e0b;border-radius:9px;font-size:.78rem}
.feed-item .tx{color:#e5e7eb}
.feed-item .tx strong{color:#fff}
.feed-item .tm{font-size:.65rem;color:#6b7280;margin-top:2px}
.empty{text-align:center;padding:2rem 1rem;color:#94a3b8;font-size:.85rem}
.empty i{font-size:1.6rem;color:#f59e0b;opacity:.4;display:block;margin-bottom:.5rem}
.filter-bar{display:flex;gap:.6rem;flex-wrap:wrap;align-items:end;padding:1rem;background:rgba(15,23,42,0.4);border-radius:16px;border:1px solid rgba(245,158,11,0.12);margin-bottom:1.5rem}
.filter-bar > div{display:flex;flex-direction:column;gap:.25rem;flex:1;min-width:130px}
@media(max-width:768px){.nav-link{padding:.5rem .8rem!important;font-size:.85rem}.metric-value{font-size:1.5rem}.chart-box{height:220px}}
</style></head><body>
<nav class="navbar navbar-expand-lg fixed-top"><div class="container-fluid">
<a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="fas fa-hotel"></i> Rori Hotel</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">
<a class="nav-link" href="{{ url_for('dashboard') }}"><i class="fas fa-home"></i> Dashboard</a>
<a class="nav-link" href="{{ url_for('request_create') }}"><i class="fas fa-plus-circle"></i> New</a>
<a class="nav-link" href="{{ url_for('requests_list') }}"><i class="fas fa-tasks"></i> Requests</a>
<a class="nav-link" href="{{ url_for('workorders_list') }}"><i class="fas fa-clipboard-list"></i> Work Orders</a>
<a class="nav-link" href="{{ url_for('rooms_list') }}"><i class="fas fa-door-open"></i> Rooms</a>
<a class="nav-link" href="{{ url_for('areas_list') }}"><i class="fas fa-map-marked-alt"></i> Areas</a>
<a class="nav-link" href="{{ url_for('inventory_list') }}"><i class="fas fa-boxes"></i> Inventory</a>
<a class="nav-link" href="{{ url_for('suppliers_list') }}"><i class="fas fa-truck"></i> Suppliers</a>
<a class="nav-link" href="{{ url_for('employees_list') }}"><i class="fas fa-users"></i> Employees</a>
{% if current_user.role == 'ADMIN' %}
<a class="nav-link" href="{{ url_for('admin_users') }}"><i class="fas fa-user-cog"></i> Users</a>
<a class="nav-link" href="{{ url_for('audit_logs') }}"><i class="fas fa-history"></i> Audit</a>
<a class="nav-link" href="{{ url_for('deleted_requests') }}"><i class="fas fa-trash"></i> Deleted</a>
<a class="nav-link" href="{{ url_for('backup_page') }}"><i class="fas fa-archive"></i> Backup</a>
{% endif %}
<a class="nav-link" href="{{ url_for('reports') }}"><i class="fas fa-chart-bar"></i> Reports</a>
<a class="nav-link" href="{{ url_for('notifications') }}"><i class="fas fa-bell"></i> Notifications</a>
<a class="nav-link" href="{{ url_for('profile') }}"><i class="fas fa-user-circle"></i> {{ current_user.full_name or current_user.username }}</a>
<a class="nav-link" href="{{ url_for('logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a>
</div></div></div></nav>
<div class="container mt-4">
<div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
<div>
<h2 style="color:#f59e0b;font-weight:800;margin:0"><i class="fas fa-chart-line"></i> Central Maintenance Dashboard</h2>
<p style="color:#94a3b8;font-size:.85rem;margin:.25rem 0 0">All departments · Real-time analytics</p>
</div>
<a href="{{ url_for('request_create') }}" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a>
</div>
<form method="get" class="filter-bar">
<div><label class="form-label">From</label><input type="date" class="form-control" name="date_from" value="{{ filters.get('date_from','') }}"></div>
<div><label class="form-label">To</label><input type="date" class="form-control" name="date_to" value="{{ filters.get('date_to','') }}"></div>
<div><label class="form-label">Department</label>
<select class="form-select" name="department">
<option value="">All</option>
{% for d in all_departments %}<option value="{{ d.id }}" {% if filters.get('department') == d.id|string %}selected{% endif %}>{{ d.name }}</option>{% endfor %}
</select></div>
<div><label class="form-label">Category</label>
<select class="form-select" name="category">
<option value="">All</option>
{% for c in all_categories %}<option value="{{ c.id }}" {% if filters.get('category') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
</select></div>
<div><label class="form-label">Status</label>
<select class="form-select" name="status">
<option value="">All</option>
{% for s in ['Pending','Pending HK Approval','Approved','Assigned','In Progress','Completed','Verified','Closed','Rejected'] %}
<option value="{{ s }}" {% if filters.get('status') == s %}selected{% endif %}>{{ s }}</option>{% endfor %}
</select></div>
<div style="flex:0"><button class="btn btn-primary" type="submit"><i class="fas fa-filter"></i> Apply</button></div>
<div style="flex:0"><a class="btn btn-sm" href="{{ url_for('dashboard') }}" style="background:#475569;color:#fff;padding:.65rem 1.2rem;border-radius:40px;font-weight:600;font-size:.85rem">Reset</a></div>
</form>
<div class="row g-3 mb-4">
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clipboard-list"></i></div><div class="metric-value">{{ kpis.total }}</div><div class="metric-label">Total</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#f59e0b"><i class="fas fa-hourglass-half"></i></div><div class="metric-value">{{ kpis.pending }}</div><div class="metric-label">Pending</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#22c55e"><i class="fas fa-circle-check"></i></div><div class="metric-value">{{ kpis.completed }}</div><div class="metric-label">Completed</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#3b82f6"><i class="fas fa-percent"></i></div><div class="metric-value">{{ kpis.completion_rate }}%</div><div class="metric-label">Rate</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#06b6d4"><i class="fas fa-clock"></i></div><div class="metric-value" style="font-size:1.3rem">{{ kpis.avg_resolution }}</div><div class="metric-label">Avg Time</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#ef4444"><i class="fas fa-toolbox"></i></div><div class="metric-value">{{ work_orders.total }}</div><div class="metric-label">Work Orders</div></div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-8">
<div class="card"><h5 class="mb-3"><i class="fas fa-chart-area"></i> Request Trends</h5>
<div class="chart-box tall"><canvas id="chartTrends"></canvas></div>
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-chart-pie"></i> Status Distribution</h5>
<div class="chart-box donut"><canvas id="chartStatus"></canvas></div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-building"></i> Requests by Department</h5>
<div class="chart-box"><canvas id="chartDept"></canvas></div>
</div>
</div>
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-check-double"></i> Completion % by Department</h5>
<div class="chart-box"><canvas id="chartDeptCompletion"></canvas></div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-fire"></i> Priority Distribution</h5>
<div class="chart-box donut"><canvas id="chartPriority"></canvas></div>
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-tags"></i> Categories</h5>
<div class="chart-box"><canvas id="chartCategories"></canvas></div>
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-layer-group"></i> By Floor</h5>
<div class="chart-box"><canvas id="chartFloors"></canvas></div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-chart-bar"></i> Department Share (%)</h5>
{% if chart_data.departments.labels|length > 0 %}
<div class="prog-list">
{% for i in range(chart_data.departments.labels|length) %}
<div class="prog-row">
<div class="prog-top"><span class="nm">{{ chart_data.departments.labels[i] }}</span>
<span class="ct">{{ chart_data.departments.values[i] }} · {{ chart_data.departments.percentages[i] }}%</span></div>
<div class="prog-bar"><span style="width:{{ chart_data.departments.percentages[i] }}%"></span></div>
</div>
{% endfor %}
</div>
{% else %}<div class="empty"><i class="fas fa-inbox"></i>No data available</div>{% endif %}
</div>
</div>
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-users-gear"></i> Technician Workload</h5>
{% if technician_workload|length > 0 %}
<div class="table-responsive"><table class="table table-hover">
<thead><tr><th>Technician</th><th>Assigned</th><th>In Progress</th><th>Completed</th><th>Avg Time</th></tr></thead>
<tbody>{% for t in technician_workload %}
<tr><td><strong>{{ t.name }}</strong><br><small style="color:#94a3b8">{{ t.role }}</small></td>
<td><span class="badge" style="background:#3b82f6">{{ t.assigned }}</span></td>
<td><span class="badge" style="background:#f59e0b">{{ t.in_progress }}</span></td>
<td><span class="badge" style="background:#22c55e">{{ t.completed }}</span></td>
<td>{{ t.avg_resolution }}</td></tr>
{% endfor %}</tbody></table></div>
{% else %}<div class="empty"><i class="fas fa-users"></i>No technicians</div>{% endif %}
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-8">
<div class="card">
<div class="d-flex justify-content-between align-items-center mb-3">
<h5 style="margin:0"><i class="fas fa-clock-rotate-left"></i> Recent Requests</h5>
<a href="{{ url_for('requests_list') }}" class="btn btn-sm" style="background:#475569;color:#fff;padding:.35rem .9rem;border-radius:20px;font-weight:600;font-size:.75rem">View All</a>
</div>
{% if recent_requests|length > 0 %}
<div class="table-responsive"><table class="table table-hover">
<thead><tr><th>Request</th><th>Department</th><th>Requested By</th><th>Location</th><th>Priority</th><th>Status</th><th>Signature</th><th>Date</th><th></th></tr></thead>
<tbody>{% for r in recent_requests %}
<tr>
    <td><a href="{{ url_for('request_detail', req_id=r.id) }}" style="color:#f59e0b;font-weight:600">{{ r.request_no }}</a></td>
    <td>{{ r.department.name if r.department else '—' }}</td>
    <td>{{ r.requested_by.full_name if r.requested_by else '—' }}</td>
    <td>{{ r.location_name }}</td>
    <td><span class="badge" style="background:{{ '#ef4444' if r.priority=='URGENT' else '#f59e0b' if r.priority=='HIGH' else '#3b82f6' if r.priority=='MEDIUM' else '#22c55e' }}">{{ r.priority }}</span></td>
    <td><span class="badge" style="background:{{ '#22c55e' if r.status in ['Completed','Verified','Closed'] else '#f59e0b' if r.status in ['Pending','Pending HK Approval'] else '#3b82f6' if r.status=='Approved' else '#8b5cf6' if r.status in ['Assigned','In Progress'] else '#6b7280' }}">{{ r.status }}</span></td>
    <td>
        {% if r.signature_status == 'SIGNED' %}
        <span class="badge" style="background:#22c55e"><i class="fas fa-check"></i> Signed</span>
        {% else %}
        <span class="badge" style="background:#6b7280">Unsigned</span>
        {% endif %}
    </td>
    <td style="color:#94a3b8;font-size:.78rem">{{ r.created_at.strftime('%b %d') if r.created_at else '—' }}</td>
    <td><a href="{{ url_for('request_detail', req_id=r.id) }}" class="btn btn-sm" style="background:#475569;color:#fff;padding:.2rem .6rem;border-radius:8px;font-size:.7rem">Open</a></td>
</tr>
{% endfor %}</tbody></table></div>
{% else %}<div class="empty"><i class="fas fa-inbox"></i>No requests</div>{% endif %}
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-wave-square"></i> Activity</h5>
{% if recent_activity|length > 0 %}
<div class="feed">
{% for a in recent_activity %}
<div class="feed-item"><i class="fas fa-bolt" style="color:#f59e0b;margin-top:.15rem"></i>
<div style="flex:1"><div class="tx"><strong>{{ a.user }}</strong> — {{ a.action }}</div>
<div class="tm">{{ a.time }}</div></div></div>
{% endfor %}
</div>
{% else %}<div class="empty"><i class="fas fa-wave-square"></i>No activity</div>{% endif %}
</div>
<div class="card"><h5 class="mb-3"><i class="fas fa-boxes"></i> Inventory Snapshot</h5>
<div class="prog-list">
<div class="prog-row"><div class="prog-top"><span class="nm">Total Parts</span><span class="ct">{{ inventory.total_parts }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Low Stock</span><span class="ct" style="color:#f59e0b">{{ inventory.low_stock }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Out of Stock</span><span class="ct" style="color:#ef4444">{{ inventory.out_of_stock }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Total Value</span><span class="ct">{{ inventory.total_value }}</span></div></div>
</div>
</div>
</div>
</div>
</div>
</div>
<script>
window.DASHBOARD_DATA = {{ chart_data|tojson }};
(function(){
'use strict';
if(typeof Chart === 'undefined') return;
var D = window.DASHBOARD_DATA || {};
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = 'rgba(245,158,11,0.1)';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;
var TT = {backgroundColor:'rgba(15,23,42,0.97)', borderColor:'rgba(245,158,11,0.5)',
borderWidth:1, titleColor:'#fff', bodyColor:'#e5e7eb', padding:11, cornerRadius:10};
var C = {amber:'#f59e0b', green:'#22c55e', blue:'#3b82f6', purple:'#8b5cf6', cyan:'#06b6d4', pink:'#ec4899', red:'#ef4444', gray:'#9ca3af'};
var PALETTE = [C.amber, C.blue, C.green, C.purple, C.cyan, C.pink, C.red, '#84cc16', '#f97316', '#a855f7', '#0ea5e9', C.gray];
function gr(c, a, b){var g = c.createLinearGradient(0,0,0,340); g.addColorStop(0,a); g.addColorStop(1,b); return g;}
function em(el, i, m){if(!el || !el.parentElement) return; el.parentElement.innerHTML='<div class="empty"><i class="fas '+i+'"></i>'+m+'</div>';}
(function(){
var el = document.getElementById('chartTrends');
if(!el) return;
var t = D.trends;
if(!t || !t.labels || !t.labels.length){em(el,'fa-chart-area','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'line', data:{labels:t.labels, datasets:[
{label:'Total', data:t.total, borderColor:C.amber, borderWidth:2.5, fill:true,
backgroundColor:gr(c,'rgba(245,158,11,0.35)','rgba(245,158,11,0.01)'),
tension:0.4, pointRadius:0, pointHoverRadius:6},
{label:'Completed', data:t.completed, borderColor:C.green, borderWidth:2.2, fill:true,
backgroundColor:gr(c,'rgba(34,197,94,0.2)','rgba(34,197,94,0.01)'),
tension:0.4, pointRadius:0, pointHoverRadius:5},
{label:'Pending', data:t.pending, borderColor:C.red, borderWidth:2, fill:false, tension:0.4, pointRadius:0, pointHoverRadius:5},
{label:'In Progress', data:t.in_progress, borderColor:C.purple, borderWidth:2, fill:false, tension:0.4, pointRadius:0, pointHoverRadius:5}
]}, options:{responsive:true, maintainAspectRatio:false, interaction:{intersect:false, mode:'index'},
plugins:{legend:{position:'top', align:'end', labels:{boxWidth:8, boxHeight:8, padding:14, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT},
scales:{x:{grid:{color:'rgba(245,158,11,0.05)'}, ticks:{maxRotation:0, autoSkip:true, maxTicksLimit:10}},
y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartStatus');
if(!el) return;
var s = D.statuses;
if(!s || !s.labels || !s.labels.length){em(el,'fa-chart-pie','No data available'); return;}
var map = {'Pending':C.amber, 'Pending HK Approval':C.amber, 'Approved':C.blue, 'Assigned':C.purple, 'In Progress':C.purple,
'Completed':C.green, 'Verified':C.cyan, 'Closed':'#16a34a', 'Rejected':C.red, 'Overdue':C.red};
new Chart(el.getContext('2d'), {type:'doughnut', data:{labels:s.labels, datasets:[
{data:s.values, backgroundColor:s.labels.map(function(l){return map[l] || C.gray;}), borderColor:'#1e293b', borderWidth:3, hoverOffset:8}
]}, options:{responsive:true, maintainAspectRatio:false, cutout:'68%',
plugins:{legend:{position:'bottom', labels:{boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}}});
})();
(function(){
var el = document.getElementById('chartDept');
if(!el) return;
var d = D.departments;
if(!d || !d.labels || !d.labels.length){em(el,'fa-building','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:d.labels, datasets:[
{label:'Requests', data:d.values, backgroundColor:gr(c,'rgba(245,158,11,0.95)','rgba(236,72,153,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:36}
]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT},
scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:10}}},
y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartDeptCompletion');
if(!el) return;
var d = D.dept_completion;
if(!d || !d.labels || !d.labels.length){em(el,'fa-check-double','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:d.labels, datasets:[
{label:'Total', data:d.totals, backgroundColor:'rgba(148,163,184,0.35)', borderRadius:8, borderSkipped:false, maxBarThickness:28},
{label:'Completed', data:d.completed, backgroundColor:gr(c,'rgba(34,197,94,0.95)','rgba(16,185,129,0.5)'), borderRadius:8, borderSkipped:false, maxBarThickness:28}
]}, options:{responsive:true, maintainAspectRatio:false,
plugins:{legend:{position:'top', labels:{boxWidth:8, boxHeight:8, padding:10, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT},
scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:10}}},
y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartPriority');
if(!el) return;
var p = D.priorities;
if(!p || !p.labels || !p.labels.length){em(el,'fa-fire','No data available'); return;}
var map = {'URGENT':C.red, 'HIGH':C.amber, 'MEDIUM':C.blue, 'LOW':C.green};
new Chart(el.getContext('2d'), {type:'doughnut', data:{labels:p.labels, datasets:[
{data:p.values, backgroundColor:p.labels.map(function(l){return map[l] || C.gray;}), borderColor:'#1e293b', borderWidth:3, hoverOffset:8}
]}, options:{responsive:true, maintainAspectRatio:false, cutout:'68%',
plugins:{legend:{position:'bottom', labels:{boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}}});
})();
(function(){
var el = document.getElementById('chartCategories');
if(!el) return;
var x = D.categories;
if(!x || !x.labels || !x.labels.length){em(el,'fa-tags','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:x.labels, datasets:[
{label:'Requests', data:x.values, backgroundColor:gr(c,'rgba(56,189,248,0.95)','rgba(139,92,246,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:30}
]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT},
scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:9}}},
y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartFloors');
if(!el) return;
var x = D.floors;
if(!x || !x.labels || !x.labels.length){em(el,'fa-layer-group','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:x.labels, datasets:[
{label:'Requests', data:x.values, backgroundColor:gr(c,'rgba(139,92,246,0.95)','rgba(56,189,248,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:36}
]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT},
scales:{x:{grid:{display:false}}, y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});
})();
})();
</script>
</body></html>"""

# ══════════════════════════════════════════ DEPARTMENT DASHBOARD
@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    dept_id = current_user.department_id
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_id:
        q = q.filter(db.or_(MaintenanceRequest.department_id == dept_id,
                            MaintenanceRequest.requested_by_id == current_user.id))
    else:
        q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    total = len(reqs)
    pending = sum(1 for r in reqs if r.status in ["Pending", "Pending HK Approval"])
    approved = sum(1 for r in reqs if r.status in ["Approved","Assigned"])
    in_progress = sum(1 for r in reqs if r.status == "In Progress")
    completed = sum(1 for r in reqs if r.status == "Completed")
    verified = sum(1 for r in reqs if r.status == "Verified")
    closed = sum(1 for r in reqs if r.status == "Closed")
    rejected = sum(1 for r in reqs if r.status == "Rejected")
    overdue = sum(1 for r in reqs if r.is_overdue)
    
    def bd(st): return {"Pending":"warning","Pending HK Approval":"warning","Approved":"primary","Assigned":"info","In Progress":"info",
                        "Completed":"success","Verified":"success","Closed":"secondary",
                        "Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
                        
    rows = []
    for r in reqs[:30]:
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:#f59e0b">' + str(r.request_no) + '</a></td>'
                    '<td>' + str(r.location_name) + '</td><td>' + str(r.priority) + '</td>'
                    '<td><span class="badge bg-' + bd(r.status) + '">' + str(r.status) + '</span></td>'
                    '<td>' + (r.created_at.strftime("%Y-%m-%d") if r.created_at else "—") + '</td></tr>')
                    
    dept_name = current_user.department.name if current_user.department else "My Department"
    c = ('<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">'
         '<h3 style="color:#f59e0b;margin:0"><i class="fas fa-building"></i> ' + str(dept_name) + ' Dashboard</h3>'
         '<a href="' + url_for("request_create") + '" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a></div>'
         '<div class="row g-3 mb-4">'
         '<div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">' + str(total) + '</div><div class="metric-label">Total</div></div></div>'
         '<div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value" style="color:#f59e0b">' + str(pending) + '</div><div class="metric-label">Pending</div></div></div>'
         '<div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value" style="color:#8b5cf6">' + str(in_progress) + '</div><div class="metric-label">In Progress</div></div></div>'
         '<div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value" style="color:#22c55e">' + str(completed + verified + closed) + '</div><div class="metric-label">Done</div></div></div>'
         '</div>'
         '<div class="card"><h5 style="color:#f59e0b"><i class="fas fa-tasks"></i> My Requests</h5>'
         '<div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>Request #</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" class="text-center">No requests yet. <a href="' + url_for("request_create") + '">Create one</a></td></tr>') + '</tbody>'
         '</table></div></div>')
    return page("Department Dashboard", c)

# ══════════════════════════════════════════ EMPLOYEE DASHBOARD
@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    reqs = MaintenanceRequest.query.filter_by(is_deleted=False, requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    def bd(st): return {"Pending":"warning","Pending HK Approval":"warning","Approved":"primary","Assigned":"info","In Progress":"info",
                        "Completed":"success","Verified":"success","Closed":"secondary",
                        "Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    rows = []
    for r in reqs[:30]:
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:#f59e0b">' + str(r.request_no) + '</a></td>'
                    '<td>' + str(r.location_name) + '</td><td>' + str(r.priority) + '</td>'
                    '<td><span class="badge bg-' + bd(r.status) + '">' + str(r.status) + '</span></td>'
                    '<td>' + (r.created_at.strftime("%Y-%m-%d") if r.created_at else "—") + '</td></tr>')
    c = ('<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">'
         '<h3 style="color:#f59e0b;margin:0"><i class="fas fa-home"></i> My Dashboard</h3>'
         '<a href="' + url_for("request_create") + '" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a></div>'
         '<div class="card"><h5 style="color:#f59e0b"><i class="fas fa-tasks"></i> My Requests</h5>'
         '<div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>Request #</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" class="text-center">No requests yet</td></tr>') + '</tbody>'
         '</table></div></div>')
    return page("Employee Dashboard", c)

# ══════════════════════════════════════════ WORK ORDERS
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
    if current_user.role in STAFF_ROLES:
        wos = WorkOrder.query.filter(db.or_(WorkOrder.assigned_to_id == current_user.id,
                                            WorkOrder.assigned_to_id.is_(None))).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    rows = []
    for wo in wos:
        assigned = wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned"
        badge = "success" if wo.status in ["Completed","Verified"] else "warning" if wo.status in ["Pending","Assigned"] else "info"
        rows.append('<tr><td><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:#f59e0b">' + str(wo.work_order_no) + '</a></td>'
                    '<td>' + str(wo.request.location_name if wo.request else "—") + '</td>'
                    '<td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td>'
                    '<td>' + str(wo.request.department.name if wo.request and wo.request.department else "—") + '</td>'
                    '<td>' + str(wo.request.priority if wo.request else "—") + '</td>'
                    '<td><span class="badge bg-' + badge + '">' + str(wo.status) + '</span></td>'
                    '<td>' + str(assigned) + '</td></tr>')
    c = ('<h3 style="color:#f59e0b"><i class="fas fa-clipboard-list"></i> Work Orders</h3>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>Order #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Assigned</th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" class="text-center">No work orders</td></tr>') + '</tbody></table></div></div>')
    return page("Work Orders", c)

@app.route("/workorders/new", methods=["GET","POST"])
@role_required("MANAGER","ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = get_one(MaintenanceRequest, req_id) if req_id else None
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    uo = "".join('<option value="' + str(u.id) + '">' + str(u.full_name or u.username) + ' — ' + str(u.role) + '</option>' for u in staff)
    if request.method == "POST":
        try:
            request_id = request.form.get("request_id", type=int)
            assigned_to_id = request.form.get("assigned_to_id", type=int)
            wp = request.form.get("work_performed","")
            if not assigned_to_id:
                flash("Please select a technician","danger"); return redirect(url_for("workorder_create", request_id=request_id))
            req = get_or_404(MaintenanceRequest, request_id)
            assigned_user = get_one(User, assigned_to_id)
            existing = WorkOrder.query.filter_by(request_id=req.id).filter(WorkOrder.status != "Completed").first()
            if existing:
                wo = existing; wo.assigned_to_id = assigned_to_id; wo.status = "Assigned"
                if wp: wo.work_performed = wp
            else:
                wo = WorkOrder(work_order_no=work_order_no_generator(), request_id=req.id,
                               assigned_to_id=assigned_to_id, status="Assigned", work_performed=wp)
                db.session.add(wo); db.session.flush()
            log_audit("Create","WorkOrder",wo.id,new_value=wo.work_order_no)
            req.status = "Assigned"; req.assigned_to_id = assigned_to_id
            if req.status == "Pending": req.status = "Assigned"
            log_status_change(req.id,"Assigned",notes="Assigned to " + str(assigned_user.full_name if assigned_user else "?"))
            if assigned_user: notify_assigned_staff(req, wo, assigned_user)
            if req.requested_by_id:
                notify_users([req.requested_by_id], req.id, "Work Assigned",
                             "Staff assigned to " + str(req.request_no), "Assigned",
                             link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit(); flash("✅ Assigned!","success")
            return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e:
            db.session.rollback(); print("WO assign: " + traceback.format_exc())
            flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_create", request_id=request_id))
            
    c = ('<h3 style="color:#f59e0b">Assign Staff to Work Order</h3>'
         '<div class="card"><form method="post">'
         '<input type="hidden" name="request_id" value="' + str(req.id if req else "") + '">'
         '<div class="mb-3"><label class="form-label">Request</label><input class="form-control" value="' + str(req.request_no if req else "") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Department</label><input class="form-control" value="' + str(req.department.name if req and req.department else "—") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Location</label><input class="form-control" value="' + str(req.location_name if req else "") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Requested By</label><input class="form-control" value="' + str(req.requested_by.full_name if req and req.requested_by else "—") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Assign To *</label><select class="form-select" name="assigned_to_id" required><option value="">-- Select Technician --</option>' + uo + '</select></div>'
         '<div class="mb-3"><label class="form-label">Instructions</label><textarea class="form-control" name="work_performed" rows="3"></textarea></div>'
         '<button class="btn btn-primary"><i class="fas fa-save"></i> Assign</button></form></div>')
    return page("Assign Work Order", c)

@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
    can_parts = (current_user.role in ["MANAGER","ADMIN"] or
                 (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))
    pr, pt = [], 0
    for p in parts:
        pname = p.part.part_name if p.part else "Part #" + str(p.part_id)
        psupp = p.part.supplier.company_name if p.part and p.part.supplier else "—"
        pun = p.part.unit if p.part else "pcs"
        lt = (p.quantity or 0) * (p.unit_cost or 0); pt += lt
        rem = ""
        if can_parts and wo.status in ["Assigned","In Progress"]:
            rem = '<form method="post" action="' + url_for("workorder_part_remove", wo_id=wo.id, part_id=p.id) + '" style="display:inline" onsubmit="return confirm(\'Remove?\')"><button type="submit" class="btn btn-sm btn-danger"><i class="fas fa-times"></i></button></form>'
        pr.append('<tr><td>' + str(pname) + '</td><td>' + str(psupp) + '</td><td>' + str(p.quantity) + '</td><td>' + str(pun) + '</td><td>' + str(p.unit_cost or 0) + '</td><td>' + str(lt) + '</td><td>' + rem + '</td></tr>')
    apb = ""
    if can_parts and wo.status in ["Assigned","In Progress"]:
        apb = '<a class="btn btn-sm btn-primary" href="' + url_for("workorder_part_add", wo_id=wo.id) + '"><i class="fas fa-plus"></i> Add Part</a>'
    parts_card = ('<div class="card"><div class="d-flex justify-content-between align-items-center mb-2">'
                  '<h5 style="color:#f59e0b;margin:0"><i class="fas fa-boxes"></i> Parts</h5>' + apb + '</div>'
                  '<div class="table-responsive"><table class="table"><thead><tr><th>Part</th><th>Supplier</th><th>Qty</th><th>Unit</th><th>Cost</th><th>Total</th><th></th></tr></thead>'
                  '<tbody>' + ("".join(pr) if pr else '<tr><td colspan="7" class="text-center">No parts</td></tr>') + '</tbody></table></div>'
                  '<p class="text-end mb-0"><b>Total: ' + str(pt) + '</b></p></div>')
    ch = ""
    if wo.completion_photo:
        ch = '<div class="mt-3"><h6>📸 Completion Photo:</h6><a href="/static/uploads/maintenance/' + str(wo.completion_photo) + '" target="_blank"><img src="/static/uploads/maintenance/' + str(wo.completion_photo) + '" class="img-fluid rounded" style="max-height:250px"></a></div>'
    actions = ""
    if current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id:
        if wo.status == "Assigned":
            actions += '<form method="post" action="' + url_for("workorder_start", wo_id=wo.id) + '"><button type="submit" class="btn btn-warning mb-2 w-100"><i class="fas fa-play"></i> Start Work</button></form>'
        if wo.status == "In Progress":
            actions += '<a href="' + url_for("workorder_complete", wo_id=wo.id) + '" class="btn btn-success mb-2 w-100"><i class="fas fa-check"></i> Complete Work</a>'
    if (current_user.role == "ADMIN" or current_user.role == "MANAGER") and wo.status == "Completed":
        actions += '<form method="post" action="' + url_for("workorder_verify", wo_id=wo.id) + '"><button type="submit" class="btn btn-info mb-2 w-100"><i class="fas fa-check-double"></i> ✅ Verify</button></form>'
        
    c = ('<div class="d-flex justify-content-between mb-3"><h3 style="color:#f59e0b">🔧 Work Order ' + str(wo.work_order_no) + '</h3>'
         '<a href="' + url_for("workorders_list") + '" class="btn btn-secondary btn-sm"><i class="fas fa-arrow-left"></i> Back</a></div>'
         '<div class="row"><div class="col-md-8"><div class="card"><table class="table">'
         '<tr><th style="width:150px;color:#94a3b8">Request</th><td>' + str(wo.request.request_no if wo.request else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Department</th><td>' + str(wo.request.department.name if wo.request and wo.request.department else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Location</th><td>' + str(wo.request.location_name if wo.request else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Item</th><td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Priority</th><td>' + str(wo.request.priority if wo.request else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Requested By</th><td><strong>' + str(wo.request.requested_by.full_name if wo.request and wo.request.requested_by else "—") + '</strong></td></tr>'
         '<tr><th style="color:#94a3b8">Status</th><td><span class="badge bg-info">' + str(wo.status) + '</span></td></tr>'
         '<tr><th style="color:#94a3b8">Assigned To</th><td>' + str(wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Instructions</th><td>' + str(wo.work_performed or "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Completion Notes</th><td>' + str(wo.completion_notes or "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Labor Hours</th><td>' + str(wo.labor_hours) + '</td></tr>'
         '</table>' + ch + '</div>' + parts_card + '</div>'
         '<div class="col-md-4"><div class="card"><h5 style="color:#f59e0b">Actions</h5>'
         + (actions if actions else "<p style='color:#94a3b8'>No actions available</p>") + '</div></div></div>')
    return page("Work Order Detail", c)

@app.route("/workorders/<int:wo_id>/start", methods=["POST"])
@login_required
def workorder_start(wo_id):
    try:
        wo = get_or_404(WorkOrder, wo_id)
        if current_user.id != wo.assigned_to_id: flash("Not authorized","danger"); return redirect(url_for("workorder_detail", wo_id=wo_id))
        if wo.status != "Assigned": flash("Cannot start","warning"); return redirect(url_for("workorder_detail", wo_id=wo_id))
        wo.status = "In Progress"
        if wo.request: wo.request.status = "In Progress"
        log_status_change(wo.request_id,"In Progress",notes="Started by " + str(current_user.full_name))
        log_audit("Start","WorkOrder",wo.id,"Assigned","In Progress")
        db.session.commit(); flash("Work started","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))

@app.route("/workorders/<int:wo_id>/complete", methods=["GET","POST"])
@role_required(*STAFF_ROLES)
def workorder_complete(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if current_user.id != wo.assigned_to_id: flash("Not authorized","danger"); return redirect(url_for("workorder_detail", wo_id=wo_id))
    if wo.status != "In Progress": flash("Not in progress","warning"); return redirect(url_for("workorder_detail", wo_id=wo_id))
    if request.method == "POST":
        try:
            note = request.form.get("completion_note","").strip()
            try: hours = float(request.form.get("labor_hours","0") or "0")
            except: hours = 0.0
            if not note: flash("Completion note required","danger"); return redirect(url_for("workorder_complete", wo_id=wo_id))
            fname = None
            f = request.files.get("photo")
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit(".",1)[-1].lower()
                fname = secure_filename("wo_" + str(wo.id) + "_done_" + datetime.now().strftime("%Y%m%d%H%M%S") + "." + ext)
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            wo.completion_notes = note; wo.labor_hours = hours; wo.status = "Completed"
            wo.completed_by_id = current_user.id; wo.completed_date = datetime.utcnow()
            if fname: wo.completion_photo = fname
            if wo.request:
                wo.request.status = "Completed"; wo.request.completed_date = datetime.utcnow(); wo.request.completion_note = note
                log_status_change(wo.request_id,"Completed",notes="Completed by " + str(current_user.full_name))
                log_audit("Complete","WorkOrder",wo.id,"In Progress","Completed")
                managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"])).all()
                notify_users([u.id for u in managers], wo.request_id, "🔔 Work Completed",
                             "WO " + str(wo.work_order_no) + " ready for verification", "Completed",
                             link=url_for("workorder_detail", wo_id=wo.id))
                if wo.request and wo.request.requested_by_id:
                    notify_users([wo.request.requested_by_id], wo.request_id, "Work Completed",
                                 "Request " + str(wo.request.request_no) + " completed", "Completed",
                                 link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit(); flash("✅ Completed! Waiting for verification.","success")
            return redirect(url_for("workorder_detail", wo_id=wo_id))
        except Exception as e:
            db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_complete", wo_id=wo_id))
            
    c = ('<h3 style="color:#f59e0b">Complete Work Order ' + str(wo.work_order_no) + '</h3>'
         '<div class="card"><form method="post" enctype="multipart/form-data">'
         '<div class="mb-3"><label class="form-label">Completion Note *</label><textarea name="completion_note" class="form-control" rows="4" required></textarea></div>'
         '<div class="mb-3"><label class="form-label">Photo</label><input type="file" name="photo" accept="image/*" class="form-control"></div>'
         '<div class="mb-3"><label class="form-label">Labor Hours</label><input type="number" step="0.5" name="labor_hours" class="form-control" value="0"></div>'
         '<button class="btn btn-success btn-lg w-100"><i class="fas fa-check-circle"></i> Complete</button></form></div>')
    return page("Complete Work Order", c)

@app.route("/workorders/<int:wo_id>/verify", methods=["POST"])
@role_required("MANAGER","ADMIN")
def workorder_verify(wo_id):
    try:
        wo = get_or_404(WorkOrder, wo_id)
        if wo.status != "Completed": flash("Only completed can be verified","warning"); return redirect(url_for("workorder_detail", wo_id=wo_id))
        wo.status = "Verified"; wo.verified_by_id = current_user.id; wo.verified_date = datetime.utcnow()
        if wo.request:
            wo.request.status = "Verified"; wo.request.manager_id = current_user.id
            if not wo.request.completed_date: wo.request.completed_date = datetime.utcnow()
            log_status_change(wo.request_id,"Verified",notes="Verified by " + str(current_user.full_name))
            log_audit("Verify","WorkOrder",wo.id,"Completed","Verified")
            if wo.request:
                notify_users([wo.request.requested_by_id], wo.request_id, "✅ Verified",
                             "Request " + str(wo.request.request_no) + " verified", "Verified",
                             link=url_for("request_detail", req_id=wo.request_id))
        db.session.commit(); flash("✅ Verified!","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))

# ══════════════════════════════════════════ SUPPLIERS
def supplier_active(s):
    if s is None: return True
    if s.is_active is not None: return s.is_active
    return s.status == "Active"

def supplier_form(s, action, edit):
    def v(f): return str(getattr(s, f) or "") if s else ""
    act = supplier_active(s)
    a1 = " selected" if act else ""
    a2 = "" if act else " selected"
    return ('<h3 style="color:#f59e0b"><i class="fas fa-truck"></i> ' + ("Edit" if edit else "Add") + ' Supplier</h3>'
            '<div class="card"><form method="post" action="' + str(action) + '"><div class="row">'
            '<div class="col-md-6 mb-3"><label class="form-label">Supplier Name *</label><input type="text" class="form-control" name="company_name" value="' + v("company_name") + '" required></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Contact</label><input type="text" class="form-control" name="contact_person" value="' + v("contact_person") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + v("phone") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + v("email") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Address</label><input type="text" class="form-control" name="address" value="' + v("address") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Tax Number</label><input type="text" class="form-control" name="tax_number" value="' + v("tax_number") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Status</label><select class="form-select" name="status"><option value="Active"' + a1 + '>Active</option><option value="Inactive"' + a2 + '>Inactive</option></select></div>'
            '<div class="col-12 mb-3"><label class="form-label">Notes</label><textarea class="form-control" name="notes" rows="3">' + v("notes") + '</textarea></div>'
            '<div class="col-12 d-flex gap-2"><a href="' + url_for("suppliers_list") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
            '<button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save</button></div>'
            '</div></form></div>')

@app.route("/suppliers")
@role_required("ADMIN","MANAGER")
def suppliers_list():
    ss = Supplier.query.order_by(Supplier.company_name).all()
    rows = []
    for s in ss:
        act = supplier_active(s)
        bg = '<span class="badge bg-success">Active</span>' if act else '<span class="badge bg-secondary">Inactive</span>'
        ac = '<a class="btn btn-sm btn-info" href="' + url_for("supplier_edit", supplier_id=s.id) + '"><i class="fas fa-edit"></i> Edit</a> '
        if act:
            ac += '<form method="post" action="' + url_for("supplier_deactivate", supplier_id=s.id) + '" style="display:inline" onsubmit="return confirm(\'Deactivate?\')"><button type="submit" class="btn btn-sm btn-warning"><i class="fas fa-ban"></i></button></form>'
        rows.append('<tr><td>' + str(s.id) + '</td><td>' + str(s.company_name) + '</td><td>' + str(s.contact_person or "—") + '</td><td>' + str(s.phone or "—") + '</td><td>' + str(s.email or "—") + '</td><td>' + bg + '</td><td>' + ac + '</td></tr>')
    c = ('<h3 style="color:#f59e0b"><i class="fas fa-truck"></i> Suppliers</h3>'
         '<a class="btn btn-primary mb-3" href="' + url_for("supplier_add") + '"><i class="fas fa-plus-circle"></i> Add</a>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>ID</th><th>Name</th><th>Contact</th><th>Phone</th><th>Email</th><th>Status</th><th>Actions</th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" class="text-center">None</td></tr>') + '</tbody></table></div></div>')
    return page("Suppliers", c)

@app.route("/suppliers/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def supplier_add():
    if request.method == "POST":
        name = request.form.get("company_name","").strip()
        email = request.form.get("email","").strip()
        if not name: flash("Name required","danger"); return page("Add", supplier_form(None, url_for("supplier_add"), False))
        if email and not valid_email(email): flash("Invalid email","danger"); return page("Add", supplier_form(None, url_for("supplier_add"), False))
        if Supplier.query.filter_by(company_name=name).first(): flash("Exists","warning"); return page("Add", supplier_form(None, url_for("supplier_add"), False))
        try:
            st = request.form.get("status","Active")
            s = Supplier(company_name=name, contact_person=request.form.get("contact_person","").strip(),
                         phone=request.form.get("phone","").strip(), email=email,
                         address=request.form.get("address","").strip(),
                         tax_number=request.form.get("tax_number","").strip(),
                         notes=request.form.get("notes","").strip(),
                         status=st, is_active=(st=="Active"))
            db.session.add(s); db.session.flush()
            log_audit("Supplier Created","Supplier",s.id,new_value=name)
            db.session.commit(); flash("✅ Saved","success"); return redirect(url_for("suppliers_list"))
        except Exception as e:
            db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Add Supplier", supplier_form(None, url_for("supplier_add"), False))

@app.route("/suppliers/<int:supplier_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def supplier_edit(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    if request.method == "POST":
        name = request.form.get("company_name","").strip(); email = request.form.get("email","").strip()
        if not name: flash("Name required","danger"); return page("Edit", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))
        if email and not valid_email(email): flash("Invalid email","danger"); return page("Edit", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))
        dup = Supplier.query.filter(Supplier.company_name == name, Supplier.id != s.id).first()
        if dup: flash("Exists","warning"); return page("Edit", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))
        try:
            st = request.form.get("status","Active")
            s.company_name = name
            s.contact_person = request.form.get("contact_person","").strip()
            s.phone = request.form.get("phone","").strip()
            s.email = email
            s.address = request.form.get("address","").strip()
            s.tax_number = request.form.get("tax_number","").strip()
            s.notes = request.form.get("notes","").strip()
            s.status = st; s.is_active = (st=="Active")
            log_audit("Supplier Updated","Supplier",s.id,new_value=name)
            db.session.commit(); flash("✅ Updated","success"); return redirect(url_for("suppliers_list"))
        except Exception as e:
            db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Edit Supplier", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))

@app.route("/suppliers/<int:supplier_id>/deactivate", methods=["POST"])
@role_required("ADMIN","MANAGER")
def supplier_deactivate(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    try:
        s.is_active = False; s.status = "Inactive"
        log_audit("Supplier Deactivated","Supplier",s.id,old_value="active",new_value="inactive")
        db.session.commit(); flash("Deactivated","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("suppliers_list"))

# ══════════════════════════════════════════ INVENTORY
def part_form(p, action):
    def v(f, d=""):
        if p:
            val = getattr(p, f); return str(val if val is not None else d)
        return d
    sups = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    so = '<option value="">-- Select --</option>'
    for s in sups:
        sel = ' selected' if p and p.supplier_id == s.id else ''
        so += '<option value="' + str(s.id) + '"' + sel + '>' + str(s.company_name) + '</option>'
    return ('<h3 style="color:#f59e0b"><i class="fas fa-box"></i> ' + ("Edit" if p else "Add") + ' Part</h3>'
            '<div class="card"><form method="post" action="' + str(action) + '"><div class="row">'
            '<div class="col-md-6 mb-3"><label class="form-label">Part Name *</label><input type="text" class="form-control" name="part_name" value="' + v("part_name") + '" required></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Category</label><input type="text" class="form-control" name="category" value="' + v("category") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Quantity</label><input type="number" step="0.01" class="form-control" name="quantity" value="' + v("quantity","0") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Min Stock</label><input type="number" step="0.01" class="form-control" name="minimum_stock" value="' + v("minimum_stock","5") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Unit</label><input type="text" class="form-control" name="unit" value="' + v("unit","pcs") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" class="form-control" name="unit_cost" value="' + v("unit_cost","0") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Storage</label><input type="text" class="form-control" name="storage_location" value="' + v("storage_location") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Supplier</label><select class="form-select" name="supplier_id">' + so + '</select></div>'
            '<div class="col-12 d-flex gap-2"><a href="' + url_for("inventory_list") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
            '<button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save</button></div>'
            '</div></form></div>')

@app.route("/inventory/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def inventory_add():
    if request.method == "POST":
        name = request.form.get("part_name","").strip()
        if not name: flash("Name required","danger"); return redirect(url_for("inventory_add"))
        if InventoryPart.query.filter_by(part_name=name).first(): flash("Exists","warning"); return redirect(url_for("inventory_add"))
        try:
            p = InventoryPart(part_name=name, category=request.form.get("category","").strip(),
                              quantity=request.form.get("quantity", type=float) or 0,
                              minimum_stock=request.form.get("minimum_stock", type=float) or 5,
                              unit=request.form.get("unit","pcs").strip() or "pcs",
                              unit_cost=request.form.get("unit_cost", type=float) or 0,
                              storage_location=request.form.get("storage_location","").strip(),
                              status="Active", supplier_id=request.form.get("supplier_id", type=int))
            db.session.add(p); db.session.flush()
            log_audit("Inventory Part Created","InventoryPart",p.id,new_value=name)
            db.session.commit(); flash("✅ Saved","success"); return redirect(url_for("inventory_list"))
        except Exception as e:
            db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("inventory_add"))
    return page("Add Part", part_form(None, url_for("inventory_add")))

@app.route("/inventory/<int:part_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def inventory_edit(part_id):
    p = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        name = request.form.get("part_name","").strip()
        if not name: flash("Name required","danger"); return redirect(url_for("inventory_edit", part_id=p.id))
        dup = InventoryPart.query.filter(InventoryPart.part_name == name, InventoryPart.id != p.id).first()
        if dup: flash("Exists","warning"); return redirect(url_for("inventory_edit", part_id=p.id))
        try:
            p.part_name = name
            p.category = request.form.get("category","").strip()
            p.quantity = request.form.get("quantity", type=float) or 0
            p.minimum_stock = request.form.get("minimum_stock", type=float) or 5
            p.unit = request.form.get("unit","pcs").strip() or "pcs"
            p.unit_cost = request.form.get("unit_cost", type=float) or 0
            p.storage_location = request.form.get("storage_location","").strip()
            p.supplier_id = request.form.get("supplier_id", type=int)
            log_audit("Inventory Part Updated","InventoryPart",p.id,new_value=name)
            db.session.commit(); flash("✅ Updated","success"); return redirect(url_for("inventory_list"))
        except Exception as e:
            db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Edit Part", part_form(p, url_for("inventory_edit", part_id=p.id)))

# ══════════════════════════════════════════ WORK ORDER PARTS
def can_parts(wo):
    return (current_user.role in ["MANAGER","ADMIN"] or
            (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))

@app.route("/workorders/<int:wo_id>/parts/add", methods=["GET","POST"])
@login_required
def workorder_part_add(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_parts(wo): abort(403)
    if wo.status not in ["Assigned","In Progress"]:
        flash("Cannot add parts at this stage","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
    if request.method == "POST":
        try:
            pid = request.form.get("part_id", type=int); qty = request.form.get("quantity", type=float)
            uc = request.form.get("unit_cost", type=float)
            part = get_one(InventoryPart, pid)
            if not part: flash("Select valid part","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if not qty or qty <= 0: flash("Qty > 0","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if qty > part.quantity: flash("Only " + str(part.quantity) + " available","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if uc is None or uc < 0: uc = part.unit_cost or 0
            wop = WorkOrderPart(work_order_id=wo.id, part_id=part.id, quantity=qty, unit_cost=uc)
            part.quantity = (part.quantity or 0) - qty
            db.session.add(wop)
            log_audit("Part Added","WorkOrder",wo.id,new_value=str(part.part_name) + " x " + str(qty))
            db.session.commit(); flash("✅ Part added","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e:
            db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
    parts = InventoryPart.query.filter(InventoryPart.status == "Active", InventoryPart.quantity > 0).order_by(InventoryPart.part_name).all()
    po = "".join('<option value="' + str(p.id) + '">' + str(p.part_name) + ' (stock: ' + str(p.quantity) + ')</option>' for p in parts)
    c = ('<h3 style="color:#f59e0b">Add Part — WO ' + str(wo.work_order_no) + '</h3>'
         '<div class="card"><form method="post"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Part *</label><select class="form-select" name="part_id" required><option value="">-- Select --</option>' + po + '</select></div>'
         '<div class="col-md-3 mb-3"><label class="form-label">Qty *</label><input type="number" step="0.01" min="0.01" class="form-control" name="quantity" required></div>'
         '<div class="col-md-3 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" min="0" class="form-control" name="unit_cost"></div>'
         '<div class="col-12 d-flex gap-2"><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" class="btn btn-secondary">Cancel</a>'
         '<button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> Add</button></div></div></form></div>')
    return page("Add Part", c)

@app.route("/workorders/<int:wo_id>/parts/<int:part_id>/remove", methods=["POST"])
@login_required
def workorder_part_remove(wo_id, part_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_parts(wo): abort(403)
    if wo.status not in ["Assigned","In Progress"]: flash("Cannot remove","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
    try:
        wop = WorkOrderPart.query.filter_by(work_order_id=wo.id, id=part_id).first()
        if not wop: flash("Not found","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        part = get_one(InventoryPart, wop.part_id)
        if part: part.quantity = (part.quantity or 0) + (wop.quantity or 0)
        db.session.delete(wop)
        log_audit("Part Removed","WorkOrder",wo.id,old_value=str(part.part_name if part else "?"))
        db.session.commit(); flash("Part removed","success")
    except Exception as e:
        db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo.id))

# ══════════════════════════════════════════ NOTIFICATIONS
@app.route("/api/notifications/unread")
@login_required
def api_unread():
    c = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    latest = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).first()
    return jsonify({"unread": c, "latest_id": latest.id if latest else None,
                    "latest_title": latest.title if latest else None,
                    "server_time": datetime.utcnow().isoformat()})

@app.route("/notifications")
@login_required
def notifications():
    ns = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    rows = []
    for n in ns:
        cls = "" if n.is_read else "table-warning"
        link = n.link or "#"
        ra = '<span style="color:#22c55e">✓</span>'
        if not n.is_read: ra = '<a class="btn btn-sm btn-primary" href="/notifications/mark-read/' + str(n.id) + '">Read</a>'
        rows.append('<tr class="' + cls + '"><td><a href="' + link + '" style="color:#f59e0b;font-weight:600">' + str(n.title) + '</a></td>'
                    '<td>' + str(n.message) + '</td><td>' + str(n.notification_type) + '</td>'
                    '<td>' + (n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "") + '</td><td>' + ra + '</td></tr>')
    c = ('<h3 style="color:#f59e0b"><i class="fas fa-bell"></i> Notifications</h3>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>Title</th><th>Message</th><th>Type</th><th>Date</th><th>Action</th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" class="text-center">None</td></tr>') + '</tbody></table></div></div>')
    return page("Notifications", c)

@app.route("/notifications/mark-read/<int:n_id>", methods=["GET","POST"])
@login_required
def notification_mark_read(n_id):
    try:
        n = get_or_404(Notification, n_id)
        if n.user_id == current_user.id:
            n.is_read = True; db.session.commit()
            if n.link: return redirect(n.link)
            if n.work_order_id: return redirect(url_for("workorder_detail", wo_id=n.work_order_id))
            if n.request_id: return redirect(url_for("request_detail", req_id=n.request_id))
    except Exception as e: flash("Error: " + str(e),"danger")
    return redirect(url_for("notifications"))

# ══════════════════════════════════════════ OTHER PAGES
@app.route("/rooms")
@role_required("ADMIN","MANAGER")
def rooms_list():
    rs = Room.query.order_by(Room.room_number).all()
    rows = "".join('<tr><td>' + str(r.room_number) + '</td><td>' + str(r.floor) + '</td><td>' + str(r.status) + '</td></tr>' for r in rs)
    c = ('<h3 style="color:#f59e0b">Rooms</h3><div class="card"><table class="table">'
         '<thead><tr><th>Room</th><th>Floor</th><th>Status</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Rooms", c)

@app.route("/areas")
@role_required("ADMIN","MANAGER")
def areas_list():
    ar = Area.query.order_by(Area.name).all()
    rows = "".join('<tr><td>' + str(a.name) + '</td><td>' + str(a.department or "—") + '</td></tr>' for a in ar)
    c = ('<h3 style="color:#f59e0b">Areas</h3><div class="card"><table class="table">'
         '<thead><tr><th>Name</th><th>Dept</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Areas", c)

@app.route("/inventory")
@role_required("ADMIN","MANAGER")
def inventory_list():
    ps = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = []
    for p in ps:
        bg = 'bg-danger' if p.quantity <= 0 else 'bg-warning text-dark' if p.is_low else 'bg-success'
        label = "Out" if p.quantity <= 0 else "Low" if p.is_low else "OK"
        sn = p.supplier.company_name if p.supplier else "—"
        rows.append('<tr><td>' + str(p.part_name) + '</td><td>' + str(p.category or "—") + '</td>'
                    '<td>' + str(sn) + '</td><td>' + str(p.quantity) + '</td><td>' + str(p.unit or "pcs") + '</td>'
                    '<td>' + str(p.unit_cost or 0) + '</td><td><span class="badge ' + bg + '">' + label + '</span></td>'
                    '<td><a class="btn btn-sm btn-info" href="' + url_for("inventory_edit", part_id=p.id) + '"><i class="fas fa-edit"></i></a></td></tr>')
    c = ('<h3 style="color:#f59e0b"><i class="fas fa-boxes"></i> Inventory</h3>'
         '<a class="btn btn-primary mb-3" href="' + url_for("inventory_add") + '"><i class="fas fa-plus-circle"></i> Add Part</a>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">'
         '<thead><th>Part</th><th>Category</th><th>Supplier</th><th>Qty</th><th>Unit</th><th>Cost</th><th>Status</th><th></th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="8" class="text-center">No parts</td></tr>') + '</tbody></table></div></div>')
    return page("Inventory", c)

@app.route("/employees")
@role_required("ADMIN","MANAGER")
def employees_list():
    es = Employee.query.all()
    rows = "".join('<tr><td>' + str(e.id) + '</td><td>' + str(e.name) + '</td><td>' + str(e.job_title) + '</td><td>' + str(e.department or "—") + '</td></tr>' for e in es)
    c = ('<h3 style="color:#f59e0b">Employees</h3><div class="card"><table class="table">'
         '<thead><tr><th>ID</th><th>Name</th><th>Title</th><th>Department</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Employees", c)

@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    us = User.query.all()
    rows = "".join('<tr><td>' + str(u.username) + '</td><td>' + str(u.full_name) + '</td><td>' + str(u.role) + '</td><td>' + str(u.department.name if u.department else "—") + '</td></tr>' for u in us)
    c = ('<h3 style="color:#f59e0b">Users</h3><div class="card"><table class="table">'
         '<thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Dept</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Users", c)

@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows = "".join('<tr><td>' + str(l.user.full_name if l.user else "System") + '</td><td>' + str(l.action) + '</td><td>' + str(l.object_type or "") + '</td><td>' + (l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else "") + '</td></tr>' for l in logs)
    c = ('<h3 style="color:#f59e0b">Audit Log</h3><div class="card"><table class="table">'
         '<thead><tr><th>User</th><th>Action</th><th>Object</th><th>Date</th></tr></thead>'
         '<tbody>' + (rows if rows else '<tr><td colspan="4">No logs</td></tr>') + '</tbody></table></div>')
    return page("Audit", c)

@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    bs = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join('<tr><td>' + str(b) + '</td></tr>' for b in bs)
    c = ('<h3 style="color:#f59e0b">Backups</h3>'
         '<form method="post" action="/admin/backup/now" class="mb-3"><button class="btn btn-primary">Backup Now</button></form>'
         '<div class="card"><table class="table"><thead><tr><th>File</th></tr></thead>'
         '<tbody>' + (rows if rows else '<tr><td>None</td></tr>') + '</tbody></table></div>')
    return page("Backups", c)

@app.route("/admin/backup/now", methods=["GET","POST"])
@role_required("ADMIN")
def backup_now():
    try:
        fn = "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
        src = sqlite3.connect(os.path.join(BASE_DIR, "hotel_maintenance.db"))
        dst = sqlite3.connect(os.path.join(BACKUP_FOLDER, fn))
        with dst: src.backup(dst)
        src.close(); dst.close()
        flash("Backup created: " + fn,"success")
    except Exception as e: flash("Error: " + str(e),"danger")
    return redirect(url_for("backup_page"))

@app.route("/reports")
@login_required
def reports():
    base = MaintenanceRequest.query.filter_by(is_deleted=False)
    total = base.count()
    pending = base.filter(MaintenanceRequest.status.in_(["Pending", "Pending HK Approval"])).count()
    completed = base.filter_by(status="Completed").count()
    verified = base.filter_by(status="Verified").count()
    c = ('<h3 style="color:#f59e0b">Reports</h3><div class="row g-3 mb-4">'
         '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(total) + '</div><div class="metric-label">Total</div></div></div>'
         '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(pending) + '</div><div class="metric-label">Pending</div></div></div>'
         '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(completed) + '</div><div class="metric-label">Completed</div></div></div>'
         '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(verified) + '</div><div class="metric-label">Verified</div></div></div>'
         '</div>')
    return page("Reports", c)

# ══════════════════════════════════════════ DEBUG
@app.route("/debug")
def debug():
    return jsonify({
        "users": User.query.count(),
        "departments": Department.query.count(),
        "requests": MaintenanceRequest.query.filter_by(is_deleted=False).count(),
        "work_orders": WorkOrder.query.count(),
        "notifications": Notification.query.count(),
        "managers": [{"username": u.username, "full_name": u.full_name, "role": u.role,
                      "dept": u.department.name if u.department else None}
                     for u in User.query.filter(User.role.in_(["MANAGER","ADMIN"])).all()],
    })

# ══════════════════════════════════════════ PWA / LOGO
@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel Maintenance","short_name": "RoriMaint","start_url": "/dashboard",
                    "display": "standalone","background_color": "#0f172a","theme_color": "#f59e0b","icons": []})

@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('install',e=>self.skipWaiting());", mimetype="application/javascript")

@app.route("/logo.png")
def logo():
    p = os.path.join(app.root_path, "file_00000000d93c821094a2e3f7dced7c77.png")
    if os.path.exists(p): return send_file(p, mimetype="image/png")
    return Response("", mimetype="image/png")

# ══════════════════════════════════════════ ERRORS
@app.errorhandler(403)
def e403(e): return page("Forbidden",'<div class="alert alert-danger">Access denied.</div>'), 403
@app.errorhandler(404)
def e404(e): return page("Not Found",'<div class="alert alert-warning">Page not found.</div>'), 404
@app.errorhandler(405)
def e405(e): return page("Method Not Allowed",'<div class="alert alert-danger">Method not allowed.</div>'), 405
@app.errorhandler(500)
def e500(e):
    tb = traceback.format_exc(); print("500 ERROR: " + tb)
    return "<h1>500 Error</h1><pre>" + tb + "</pre>", 500

# ══════════════════════════════════════════ INIT
with app.app_context():
    ensure_database_schema()
    seed_data()
    print("🚀 App initialized")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)