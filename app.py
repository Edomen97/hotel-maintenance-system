# --- START OF FILE app.py ---
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
REQUEST_STATUSES = ["Pending", "Approved", "Assigned", "In Progress", "Completed", "Verified", "Closed", "Rejected", "Overdue"]
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
    awaiting_hk_approval = db.Column(db.Boolean, default=False)
    hk_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    hk_approved_at = db.Column(db.DateTime)
    hk_approval_status = db.Column(db.String(20))
    hk_signature_data = db.Column(db.Text)
    hk_approval_notes = db.Column(db.Text)
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
    n = Notification(user_id=user_id, request_id=request_id, work_order_id=work_order_id,
                     title=title, message=message, notification_type=ntype, link=link)
    db.session.add(n); return n


def notify_users(ids, request_id, title, message, ntype="General", link=None, work_order_id=None):
    for uid in ids:
        if uid: create_notification(uid, request_id, title, message, ntype, link, work_order_id)


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


def ensure_database_schema():
    with app.app_context():
        try:
            db.create_all()
            print("✅ Schema OK")
        except Exception as e: print("⚠️ Schema error: " + str(e))


# ══════════════════════════════════════════ PAGE TEMPLATE (With Signature Styles)
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
.container{max-width:1400px;padding:1.5rem}
.card{background:rgba(30,41,59,0.7);border:1px solid rgba(245,158,11,0.15);border-radius:20px;color:#e2e8f0;padding:1.25rem;margin-bottom:1.5rem}
.table{color:#e2e8f0}
.table thead th{color:#f59e0b;border-bottom:2px solid rgba(245,158,11,0.2);font-size:.75rem;text-transform:uppercase;padding:10px}
.table td{padding:10px;border-color:rgba(245,158,11,0.08)}
.btn{border-radius:40px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background:linear-gradient(135deg,#f59e0b,#d97706);color:#0f172a}
.btn-secondary{background:#475569;color:#fff}
.btn-sm{padding:.4rem .9rem;font-size:.85rem}
.form-control,.form-select{background:rgba(15,23,42,0.6);border:1px solid rgba(245,158,11,0.2);border-radius:12px;color:#e2e8f0;padding:.75rem 1rem}
.form-control:focus,.form-select:focus{background:rgba(15,23,42,0.9);color:#f8fafc;border-color:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,0.15)}
.form-label{color:#cbd5e1;font-weight:500}
.alert{border-radius:16px;border:none;background:rgba(30,41,59,0.7);color:#e2e8f0}
.badge{padding:.4rem .8rem;border-radius:20px;font-weight:600;font-size:.75rem}
</style></head><body>
<nav class="navbar navbar-expand-lg fixed-top"><div class="container-fluid">
<a class="navbar-brand" href=""" + (url_for('dashboard') if current_user.is_authenticated else url_for('login')) + """"><i class="fas fa-hotel"></i> Rori Hotel</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">""" + nav_html + bell_html + """</div></div>
</div></nav>
<div class="container mt-4">""" + flash_html + content + """</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""


# ══════════════════════════════════════════ AUTH & INDEX
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
    <div class="col-11 col-md-5"><div class="card p-4">
    <div class="text-center mb-4"><h3 class="fw-bold" style="color:#f59e0b"><i class="fas fa-hotel"></i> Rori Hotel</h3><p style="color:#94a3b8">የጥገና ክፍል መግቢያ</p></div>
    <form method="post"><div class="mb-3"><label class="form-label">መለያ ስም</label><input type="text" class="form-control" name="username" required autofocus></div>
    <div class="mb-4"><label class="form-label">የይለፍ ቃል</label><input type="password" class="form-control" name="password" required></div>
    <button class="btn btn-primary w-100"><i class="fas fa-sign-in-alt"></i> ግባ</button></form>
    </div></div></div>"""
    return page("Login", lh)


@app.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("login"))


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


# ══════════════════════════════════════════ REQUESTS (WITH HK NAME & SIGNATURE)
@app.route("/requests/new", methods=["GET","POST"])
@login_required
def request_create():
    depts = Department.query.order_by(Department.name).all()
    cats = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()] or sorted({r.floor for r in Room.query.all()})

    # አሁን የገባው ዩዘር የ Housekeeping ዲፓርትመንት አባል ከሆነ ኃላፊውን (ወይም ራሱን) በራስ-ሰር እንይዛለን
    is_hk_user = False
    hk_dept_name = "Housekeeping"
    default_manager_name = current_user.full_name or current_user.username
    if current_user.department and current_user.department.name.lower() == "housekeeping":
        is_hk_user = True
    elif current_user.role == "DEPARTMENT":
        dept_obj = Department.query.get(current_user.department_id) if current_user.department_id else None
        if dept_obj and dept_obj.name.lower() == "housekeeping":
            is_hk_user = True

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
            
            # Signature & Manager details
            manager_name_input = request.form.get("hk_manager_name", "").strip()
            signature_data = request.form.get("signature_data", "").strip()

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
                requested_by_id=current_user.id, department_id=did)
            
            # ዲፓርትመንቱ Housekeeping ከሆነ ስሙን እና ፊርማውን በሰንጠረዡ ውስጥ እናስገባለን
            if manager_name_input:
                req.hk_approval_notes = f"Submitted & Signed by Dept Head / Manager: {manager_name_input}"
            if signature_data:
                req.hk_signature_data = signature_data
                req.hk_approved_at = datetime.utcnow()
                req.hk_approved_by_id = current_user.id

            req.due_date = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio,24))
            db.session.add(req); db.session.flush()
            
            log_audit("Create Request","MaintenanceRequest",req.id,new_value=req.request_no)
            log_status_change(req.id,"Pending",notes="Created by " + str(current_user.full_name))
            
            db.session.commit()
            flash("✅ Request created successfully with Department Head & Digital Signature!","success")
            return redirect(url_for("requests_list"))
        except Exception as e:
            db.session.rollback(); print("Create error: " + traceback.format_exc())
            flash("Error: " + str(e),"danger"); return redirect(url_for("request_create"))

    fo = "".join('<option value="' + str(f) + '">Floor ' + str(f) + '</option>' for f in floors)
    ro = "".join('<option value="' + str(r.id) + '">Room ' + str(r.room_number) + ' (F' + str(r.floor) + ')</option>' for r in rooms)
    ao = "".join('<option value="' + str(a.id) + '">' + str(a.name) + '</option>' for a in areas)
    io_ = "".join('<option value="' + str(i.id) + '">' + str(i.name) + '</option>' for i in items)
    co = "".join('<option value="' + str(c.id) + '">' + str(c.name) + '</option>' for c in cats)
    po = "".join('<option value="' + p + '"' + (' selected' if p=="MEDIUM" else '') + '>' + p + '</option>' for p in ["URGENT","HIGH","MEDIUM","LOW"])
    
    dopt = "".join('<option value="' + str(d.id) + '">' + str(d.name) + '</option>' for d in depts)
    dhtml = ('<div class="col-md-6 mb-3"><label class="form-label">Department</label>'
             '<select class="form-select" name="department_id" id="deptSelect"><option value="">-- Select --</option>' + dopt + '</select></div>')

    c = ('<h3 style="color:#f59e0b"><i class="fas fa-plus-circle"></i> New Maintenance Request & Digital Sign-off</h3>'
         '<div class="card"><form method="post" id="reqForm"><div class="row">'
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
         '<textarea class="form-control" name="description" rows="3" required placeholder="Describe the issue…"></textarea></div>'
         
         # --- Housekeeping / Department Manager Name & Signature Section ---
         '<div class="col-12"><hr style="border-color:rgba(245,158,11,0.3)">'
         '<h5 style="color:#f59e0b"><i class="fas fa-signature"></i> Department Head / Manager Verification & Signature</h5></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Department Head / Manager Full Name *</label>'
         '<input type="text" class="form-control" name="hk_manager_name" id="hkManagerName" value="' + str(default_manager_name) + '" required></div>'
         '<div class="col-12 mb-3"><label class="form-label">Digital Signature (Draw inside the box below) *</label>'
         '<div style="border:2px dashed rgba(245,158,11,0.4); border-radius:12px; background:rgba(15,23,42,0.8); display:inline-block; position:relative;">'
         '<canvas id="sigCanvas" width="400" height="150" style="touch-action:none; cursor:crosshair; display:block;"></canvas>'
         '</div><div><button type="button" class="btn btn-sm btn-secondary mt-2" id="clearSig"><i class="fas fa-eraser"></i> Clear Signature</button></div>'
         '<input type="hidden" name="signature_data" id="signatureData"></div>'
         
         '<div class="col-12 d-flex gap-2 mt-3">'
         '<a href="' + url_for("index") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
         '<button type="submit" class="btn btn-primary" id="submitBtn"><i class="fas fa-paper-plane"></i> Submit Request & Signature</button>'
         '</div></div></form></div>'
         
         # JavaScript for Location toggling & Signature Pad Logic
         '<script>'
         'document.addEventListener("DOMContentLoaded", function() {'
         '  var lt = document.getElementById("locationType");'
         '  var rw = document.getElementById("roomWrap");'
         '  var aw = document.getElementById("areaWrap");'
         '  var fw = document.getElementById("floorWrap");'
         '  function upd(){var v = lt.value; if(v==="Room"){rw.style.display="";aw.style.display="none";fw.style.display="none";}'
         '  else{rw.style.display="none";aw.style.display="";fw.style.display="";}}'
         '  if(lt){lt.addEventListener("change",upd); upd();}'
         
         '  var canvas = document.getElementById("sigCanvas");'
         '  if(canvas){'
         '    var ctx = canvas.getContext("2d");'
         '    var drawing = false;'
         '    ctx.strokeStyle = "#f59e0b"; ctx.lineWidth = 2.5; ctx.lineCap = "round";'
         '    function getPos(e){ var rect = canvas.getBoundingClientRect(); var clientX = e.clientX || (e.touches && e.touches[0].clientX); var clientY = e.clientY || (e.touches && e.touches[0].clientY); return {x: clientX - rect.left, y: clientY - rect.top}; }'
         '    canvas.addEventListener("mousedown", function(e){ drawing=true; var p = getPos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); });'
         '    canvas.addEventListener("mousemove", function(e){ if(!drawing)return; var p = getPos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); });'
         '    window.addEventListener("mouseup", function(){ drawing=false; });'
         '    canvas.addEventListener("touchstart", function(e){ drawing=true; var p = getPos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); e.preventDefault(); });'
         '    canvas.addEventListener("touchmove", function(e){ if(!drawing)return; var p = getPos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); e.preventDefault(); });'
         '    canvas.addEventListener("touchend", function(){ drawing=false; });'
         '    document.getElementById("clearSig").addEventListener("click", function(){ ctx.clearRect(0, 0, canvas.width, canvas.height); document.getElementById("signatureData").value=""; });'
         '    document.getElementById("reqForm").addEventListener("submit", function(e){'
         '       var dataUrl = canvas.toDataURL("image/png");'
         '       document.getElementById("signatureData").value = dataUrl;'
         '    });'
         '  }'
         '});'
         '</script>')
    return page("New Request", c)


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
    
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    rows = []
    for r in reqs:
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:#f59e0b">' + str(r.request_no) + '</a></td>'
                    '<td>' + str(r.location_name) + '</td>'
                    '<td>' + str(r.working_item.name if r.working_item else "—") + '</td>'
                    '<td>' + str(r.department.name if r.department else "—") + '</td>'
                    '<td><span class="badge bg-secondary">' + str(r.priority) + '</span></td>'
                    '<td><span class="badge bg-info">' + str(r.status) + '</span></td>'
                    '<td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td></tr>')
    
    c = ('<h3 style="color:#f59e0b"><i class="fas fa-tasks"></i> Maintenance Requests</h3>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">'
         '<thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Created</th></tr></thead>'
         '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" class="text-center">No requests found</td></tr>') +
         '</tbody></table></div></div>')
    return page("Requests", c)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = get_or_404(MaintenanceRequest, req_id)
    sig_html = ""
    if req.hk_signature_data:
        sig_html = f'<tr><th style="color:#94a3b8">Dept Head / Manager Sign-off</th><td><img src="{req.hk_signature_data}" style="max-height:80px; background:#fff; padding:4px; border-radius:6px;" alt="Signature"><br><small style="color:#94a3b8">{req.hk_approval_notes or ""}</small></td></tr>'

    c = ('<div class="d-flex justify-content-between align-items-center mb-3">'
         '<h3 style="color:#f59e0b;margin:0"><i class="fas fa-clipboard-list"></i> ' + str(req.request_no) + '</h3>'
         '<a href="' + url_for("requests_list") + '" class="btn btn-secondary btn-sm"><i class="fas fa-arrow-left"></i> Back</a></div>'
         '<div class="card"><table class="table"><tbody>'
         '<tr><th style="width:200px;color:#94a3b8">Status</th><td><span class="badge bg-info">' + str(req.status) + '</span></td></tr>'
         '<tr><th style="color:#94a3b8">Department</th><td>' + str(req.department.name if req.department else "—") + '</td></tr>'
         '<tr><th style="color:#94a3b8">Location</th><td>' + str(req.location_name) + '</td></tr>'
         '<tr><th style="color:#94a3b8">Description</th><td>' + str(req.description or "—") + '</td></tr>'
         + sig_html +
         '</tbody></table></div>')
    return page("Request Details", c)


# ══════════════════════════════════════════ INVENTORY & SUPPLIERS PLACEHOLDERS
@app.route("/inventory")
@role_required("ADMIN","MANAGER")
def inventory_list():
    return page("Inventory", '<h3 style="color:#f59e0b">Inventory</h3><div class="card"><p>Inventory module active.</p></div>')


@app.route("/suppliers")
@role_required("ADMIN","MANAGER")
def suppliers_list():
    return page("Suppliers", '<h3 style="color:#f59e0b">Suppliers</h3><div class="card"><p>Suppliers module active.</p></div>')


@app.route("/reports")
@login_required
def reports():
    return page("Reports", '<h3 style="color:#f59e0b">Reports</h3><div class="card"><p>Reports module active.</p></div>')


@app.route("/dashboard")
@login_required
def dashboard():
    return page("Dashboard", '<h3 style="color:#f59e0b">Central Manager Dashboard</h3><div class="card"><p>Welcome to Rori Hotel Maintenance Command Center.</p></div>')


@app.route("/notifications")
@login_required
def notifications():
    return page("Notifications", '<h3 style="color:#f59e0b">Notifications</h3><div class="card"><p>No unread notifications.</p></div>')


# ══════════════════════════════════════════ INIT
with app.app_context():
    ensure_database_schema()
    print("🚀 App initialized with HK Signature support")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
# --- END OF FILE app.py ---