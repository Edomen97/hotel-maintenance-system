# --------------------------------------------------------------
# መስመሮች (Routes)
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
    login_html = f"""
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-11 col-md-5">
            <div class="login-card">
                <div class="text-center mb-4">
                    <img src="/logo.png" alt="Rori Hotel Logo" style="height: 50px; margin-bottom: 10px;">
                    <h3 class="fw-bold" style="color: #f59e0b;">Rori Hotel</h3>
                    <p class="text-muted" style="color: #94a3b8;">Maintenance Login</p>
                </div>
                <form method="post">
                    {csrf_input()}
                    <div class="mb-3">
                        <label class="form-label">Username</label>
                        <input type="text" class="form-control form-control-lg" name="username" placeholder="Enter username" required>
                    </div>
                    <div class="mb-4">
                        <label class="form-label">Password</label>
                        <input type="password" class="form-control form-control-lg" name="password" placeholder="********" required>
                    </div>
                    <button class="btn btn-primary btn-lg w-100"><i class="fas fa-sign-in-alt"></i> Login</button>
                </form>
                <hr class="my-4" style="border-color: rgba(245,158,11,0.15);">
                <div class="text-center small text-muted" style="color: #94a3b8;">
                    <p class="mb-1">Manager: amir | Supervisor: abebayhu | Technician: tesfahun</p>
                    <p class="mb-0">Password: 123456</p>
                </div>
            </div>
        </div>
    </div>
    """
    return page("Login", login_html)

@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))

# ---------- PRIVACY POLICY ----------
@app.route("/privacy")
def privacy():
    content = """
    <div class="container my-5" style="max-width: 800px; color: #e0e0e0;">
        <div class="card bg-dark border-secondary p-4 shadow-lg">
            <h2 class="text-warning mb-3">Privacy & Data Protection Policy</h2>
            <p class="text-muted"><small>Rori Hotel Maintenance Management System</small></p>
            <hr class="border-secondary">

            <h5 class="text-warning mt-4">1. Overview</h5>
            <p>This policy explains how Rori Hotel collects, uses, stores, and protects information within the Rori Hotel Maintenance Management System. It applies to all authorized employees, maintenance staff, managers, and administrators.</p>

            <h5 class="text-warning mt-4">2. Information We Collect</h5>
            <ul>
                <li>User information (name, username, email, role, and securely hashed password).</li>
                <li>Maintenance information (room/location, category, priority, description, assigned staff, work status).</li>
                <li>Photos uploaded to document maintenance problems or completed work.</li>
                <li>System activity records (logins, status updates, assignments, completion records).</li>
            </ul>

            <h5 class="text-warning mt-4">3. How Information Is Used</h5>
            <p>Information is used to manage maintenance requests, assign work, monitor progress, maintain maintenance history, plan preventive maintenance, and prepare internal reports.</p>

            <h5 class="text-warning mt-4">4. Data Security</h5>
            <p>Access to information is controlled according to user roles. The system uses password hashing, authentication, access control, audit logs, and data backups.</p>

            <h5 class="text-warning mt-4">5. Confidentiality</h5>
            <p>System information is confidential and must not be shared with unauthorized persons. Information will only be used for authorized hotel operations.</p>

            <h5 class="text-warning mt-4">6. User Responsibilities</h5>
            <p>Users must keep credentials secure, provide accurate information, log out after use, and maintain confidentiality.</p>

            <h5 class="text-warning mt-4">7. Policy Updates</h5>
            <p>Rori Hotel may update this policy when necessary due to system improvements, security requirements, or operational changes.</p>

            <hr class="border-secondary mt-5">

            <!-- Developer Section -->
            <div class="p-3 bg-secondary bg-opacity-20 rounded border border-secondary text-center">
                <h6 class="text-warning mb-1">👨‍💻 System Developer & Designer</h6>
                <p class="mb-1"><strong>Edom Adinew</strong></p>
                <p class="mb-0 text-muted"><small>📧 Email: edomenaadinew9615@gmail.com</small></p>
            </div>
        </div>
    </div>
    """
    return page("Privacy Policy", content)

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
    pic_url = url_for('static', filename=f'profile_pics/{user.profile_pic}') if user.profile_pic else url_for('static', filename='profile_pics/default.png')
    content = f"""
    <div class="row">
        <div class="col-md-4 text-center">
            <img src="{pic_url}" class="profile-pic img-thumbnail mb-3" alt="Profile Picture">
            <h4 style="color: #f8fafc;">{escape_html(user.full_name)}</h4>
            <p style="color: #94a3b8;">@{escape_html(user.username)} · {escape_html(user.role)}</p>
        </div>
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title"><i class="fas fa-user-edit"></i> Edit Profile</h5>
                    <form method="post" enctype="multipart/form-data">
                        {csrf_input()}
                        <div class="mb-3">
                            <label class="form-label">Email</label>
                            <input type="email" class="form-control" name="email" value="{escape_html(user.email or '')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Phone</label>
                            <input type="text" class="form-control" name="phone" value="{escape_html(user.phone or '')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Profile Picture</label>
                            <input type="file" class="form-control" name="profile_pic" accept="image/*">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">New Password (leave blank to keep current)</label>
                            <input type="password" class="form-control" name="new_password" placeholder="********">
                        </div>
                        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Changes</button>
                        <a href="/logout" class="btn btn-danger"><i class="fas fa-sign-out-alt"></i> Logout</a>
                    </form>
                </div>
            </div>
        </div>
    </div>
    """
    return page("Profile", content)

# ---------- EMPLOYEE DASHBOARD ----------
@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    try:
        requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
        total = len(requests)
        pending = sum(1 for r in requests if r.status == "Pending")
        approved = sum(1 for r in requests if r.status == "Approved")
        assigned = sum(1 for r in requests if r.status == "Assigned")
        in_progress = sum(1 for r in requests if r.status == "In Progress")
        completed = sum(1 for r in requests if r.status == "Completed")
        closed = sum(1 for r in requests if r.status == "Closed")

        rows = ""
        for r in requests:
            rows += f"""
            <tr>
            <td><a href="/requests/{r.id}" style="color: #f59e0b; text-decoration: none; font-weight: 600;">{escape_html(r.request_no)}</a></td>
            <td>{escape_html(r.description[:50] + '...' if r.description and len(r.description) > 50 else r.description or 'N/A')}</td>
            <td>{escape_html(r.department.name if r.department else 'N/A')}</td>
            <td>{escape_html(r.location_name)}</td>
            <td>{escape_html(r.category.name if r.category else 'N/A')}</td>
            <td><span class="badge bg-{'danger' if r.priority=='URGENT' else 'warning' if r.priority=='HIGH' else 'info' if r.priority=='MEDIUM' else 'secondary'}">{escape_html(r.priority)}</span></td>
            <td><span class="badge bg-{'success' if r.status in ('Completed','Closed') else 'warning' if r.status=='Pending' else 'info'}">{escape_html(r.status)}</span></td>
            <td>{escape_html(r.assigned_to.full_name if r.assigned_to else 'Not assigned')}</td>
            <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
            <td>{r.updated_at.strftime('%Y-%m-%d %H:%M') if r.updated_at else ''}</td>
            <td>{r.completed_date.strftime('%Y-%m-%d %H:%M') if r.completed_date else ''}</td>
            </tr>
            """

        content = f"""
        <h3><i class="fas fa-user-circle"></i> My Dashboard</h3>
        <p class="text-muted">Welcome, {escape_html(current_user.full_name)}!</p>

        <div class="row g-4 mb-4">
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-tasks"></i></div><div class="metric-value">{total}</div><div class="metric-label">Total Requests</div></div></div>
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clock"></i></div><div class="metric-value">{pending}</div><div class="metric-label">Pending</div></div></div>
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-circle"></i></div><div class="metric-value">{approved}</div><div class="metric-label">Approved</div></div></div>
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-user-cog"></i></div><div class="metric-value">{assigned}</div><div class="metric-label">Assigned</div></div></div>
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-spinner"></i></div><div class="metric-value">{in_progress}</div><div class="metric-label">In Progress</div></div></div>
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-double"></i></div><div class="metric-value">{completed}</div><div class="metric-label">Completed</div></div></div>
            <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-archive"></i></div><div class="metric-value">{closed}</div><div class="metric-label">Closed</div></div></div>
        </div>

        <div class="card">
            <div class="card-body">
                <h5 class="card-title"><i class="fas fa-list"></i> My Maintenance Requests</h5>
                <div class="table-responsive">
                    <table class="table table-bordered table-striped table-hover">
                        <thead>
                            <tr>
                                <th>Request ID</th><th>Issue</th><th>Department</th><th>Location</th><th>Category</th>
                                <th>Priority</th><th>Status</th><th>Assigned To</th><th>Created</th><th>Updated</th><th>Completed</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows or '<tr><td colspan="11" class="text-center">You have not submitted any requests yet.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="row mt-4 g-3">
            <div class="col-md-4"><a class="btn btn-primary w-100" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a></div>
            <div class="col-md-4"><a class="btn btn-success w-100" href="/notifications"><i class="fas fa-bell"></i> Notifications</a></div>
            <div class="col-md-4"><a class="btn btn-info w-100" href="/profile"><i class="fas fa-user-circle"></i> Profile</a></div>
        </div>
        """
        return page("My Dashboard", content)
    except Exception as e:
        flash(f"Error loading dashboard: {str(e)}", "danger")
        return redirect(url_for("dashboard"))

# ---------- DEPARTMENT DASHBOARD ----------
@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    my_requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    rows = []
    for r in my_requests:
        working_name = r.working_item.name if r.working_item else 'N/A'
        location = r.location_name if hasattr(r, 'location_name') else 'Unknown'
        status_badge = 'success' if r.status in ['Completed', 'Closed'] else 'warning' if r.status == 'Pending' else 'info'
        priority_badge = 'danger' if r.priority == 'URGENT' else 'warning' if r.priority == 'HIGH' else 'info' if r.priority == 'MEDIUM' else 'secondary'
        rows.append(f"""
        <tr>
        <td><a href="/requests/{r.id}" style="color: #f59e0b; text-decoration: none; font-weight: 600;">{escape_html(r.request_no)}</a></td>
        <td>{escape_html(r.location_name)}</td>
        <td>{escape_html(working_name)}</td>
        <td><span class="badge bg-{priority_badge}">{escape_html(r.priority)}</span></td>
        <td><span class="badge bg-{status_badge}">{escape_html(r.status)}</span></td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>""")
    content = f"""
    <h3><i class="fas fa-building"></i> Department Dashboard</h3>
    <p class="text-muted">Welcome, {escape_html(current_user.full_name)}!</p>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a>
    <div class="card">
        <div class="card-body">
            <h5 class="card-title"><i class="fas fa-list"></i> My Requests</h5>
            <div class="table-responsive">
                <table class="table table-bordered table-striped table-hover">
                    <thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead>
                    <tbody>{''.join(rows) or '<tr><td colspan="6" class="text-center">No requests yet.</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return page("Department Dashboard", content)

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

    room_options = "".join(f'<option value="{r.id}">Room {r.room_number} (Floor {r.floor})</option>' for r in rooms)
    area_options = "".join(f'<option value="{a.id}">{escape_html(a.name)}</option>' for a in areas)
    item_options = "".join(f'<option value="{i.id}">{escape_html(i.name)}</option>' for i in items)
    category_options = "".join(f'<option value="{c.id}">{escape_html(c.name)}</option>' for c in categories)
    dept_options = "".join(f'<option value="{d.id}">{escape_html(d.name)}</option>' for d in departments)

    content = f"""
    <h3><i class="fas fa-plus-circle"></i> New Maintenance Request</h3>
    <div class="card">
    <div class="card-body">
    <form method="post" enctype="multipart/form-data">
        {csrf_input()}
        <div class="row">
            <div class="col-md-6 mb-3">
                <label class="form-label">Location Type</label>
                <select class="form-select" name="location_type" id="loc_type" onchange="toggleLocation()" required>
                    <option value="Room">Room</option>
                    <option value="Hotel Area">Hotel Area</option>
                </select>
            </div>
            <div class="col-md-6 mb-3" id="room_div">
                <label class="form-label">Room</label>
                <select class="form-select" name="room_id">{room_options}</select>
            </div>
            <div class="col-md-6 mb-3" id="area_div" style="display:none">
                <label class="form-label">Area</label>
                <select class="form-select" name="area_id"><option value="">-- Select Area --</option>{area_options}</select>
            </div>
            <div class="col-md-6 mb-3">
                <label class="form-label">Department</label>
                <select class="form-select" name="department_id" required><option value="">-- Select Department --</option>{dept_options}</select>
            </div>
            <div class="col-md-6 mb-3">
                <label class="form-label">Working Item</label>
                <select class="form-select" name="working_item_id" required><option value="">-- Select Item --</option>{item_options}</select>
            </div>
            <div class="col-md-6 mb-3">
                <label class="form-label">Category</label>
                <select class="form-select" name="category_id" required><option value="">-- Select Category --</option>{category_options}</select>
            </div>
            <div class="col-md-6 mb-3">
                <label class="form-label">Priority</label>
                <select class="form-select" name="priority">
                    <option value="LOW">Low</option><option value="MEDIUM" selected>Medium</option>
                    <option value="HIGH">High</option><option value="URGENT">Urgent</option>
                </select>
            </div>
            <div class="col-md-6 mb-3">
                <label class="form-label">Due Date (optional)</label>
                <input type="datetime-local" class="form-control" name="due_date">
            </div>
            <div class="col-12 mb-3">
                <label class="form-label">Description</label>
                <textarea class="form-control" name="description" required rows="4"></textarea>
            </div>
            <div class="col-12 mb-3">
                <label class="form-label">Photo (optional)</label>
                <input type="file" class="form-control" name="photo" accept="image/*">
            </div>
            <button class="btn btn-primary"><i class="fas fa-paper-plane"></i> Submit Request</button>
        </div>
    </form>
    </div></div>
    <script>
    function toggleLocation() {{
        var type = document.getElementById('loc_type').value;
        document.getElementById('room_div').style.display = type === 'Room' ? 'block' : 'none';
        document.getElementById('area_div').style.display = type === 'Hotel Area' ? 'block' : 'none';
    }}
    </script>
    """
    return page("New Request (Public)", content)