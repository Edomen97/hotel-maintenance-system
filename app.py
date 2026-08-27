elif report_type == "inventory":
            writer.writerow(["Part Name", "Quantity", "Min Stock", "Unit Cost", "Status"])
            for p in InventoryPart.query.order_by(InventoryPart.part_name).all():
                writer.writerow([p.part_name, p.quantity, p.minimum_stock, p.unit_cost, p.status])
        elif report_type == "employees":
            writer.writerow(["ID", "Name", "Job Title", "Department"])
            for e in Employee.query.order_by(Employee.id).all():
                writer.writerow([e.id, e.name, e.job_title, e.department])
        elif report_type == "audit":
            writer.writerow(["User", "Action", "Object Type", "Object ID", "Old", "New", "Date"])
            for a in AuditLog.query.order_by(AuditLog.created_at.desc()).limit(1000).all():
                writer.writerow([a.user.full_name if a.user else "", a.action, a.object_type, a.object_id, a.old_value, a.new_value, a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else ""])
        else:
            abort(404)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={report_type}.csv"})
    except Exception as e:
        flash(f"Error exporting report: {str(e)}", "danger")
        return redirect(url_for("reports"))


# --------------------------------------------------------------
# PWA
# --------------------------------------------------------------
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
    logo_path = os.path.join(app.root_path, 'file_00000000d93c821094a2e3f7dced7c77.png')
    return send_file(logo_path, mimetype='image/png')


# --------------------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return page("Forbidden", '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> You are not allowed to view this page.</div>'), 403


@app.errorhandler(404)
def not_found(e):
    return page("Not Found", '<div class="alert alert-warning"><i class="fas fa-search"></i> The page you requested was not found.</div>'), 404


# --------------------------------------------------------------
# TEMPORARY DEBUGGING ERROR HANDLER – shows traceback
# --------------------------------------------------------------
@app.errorhandler(500)
def internal_error(e):
    import traceback
    tb = traceback.format_exc()
    return f"""
    <h1>500 Internal Server Error</h1>
    <h3>Full traceback:</h3>
    <pre style="background:#1e1e1e; color:#d4d4d4; padding:20px; border-radius:8px; overflow:auto; white-space:pre-wrap; word-wrap:break-word;">
{tb}
    </pre>
    <p><strong>Please copy this traceback and send it to the developer.</strong></p>
    """, 500


# --------------------------------------------------------------
# INIT
# --------------------------------------------------------------
with app.app_context():
    db.create_all()
    ensure_database_schema()
    seed_data()


users_data = [
    {"full_name": "አሚር አወል", "username": "amir", "role": "MANAGER"},
    {"full_name": "አበባየሁ ክፍሌ", "username": "abebayhu", "role": "SUPERVISOR"},
    {"full_name": "ተስፋሁን ነከረ", "username": "tesfahun", "role": "TECHNICIAN"},