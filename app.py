"""TaskFlow - a personal task manager built with Flask and SQLite."""
import os
import secrets
from datetime import date, datetime

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)

import db

PRIORITIES = ("low", "medium", "high")
STATUSES = ("all", "active", "completed")
SORTS = {
    "priority": "completed ASC, CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
                "due_date IS NULL, due_date ASC, id DESC",
    "due": "completed ASC, due_date IS NULL, due_date ASC, id DESC",
    "newest": "completed ASC, id DESC",
}
TITLE_MAX = 120
DESCRIPTION_MAX = 1000


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "taskflow.db"),
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)

    # ---- CSRF protection (simple per-session token) ----------------------
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            sent = request.form.get("csrf_token", "")
            if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
                abort(400, "Invalid or missing CSRF token.")

    # ---- helpers ---------------------------------------------------------
    def parse_form(form):
        """Validate task form input. Returns (data, errors)."""
        title = form.get("title", "").strip()
        description = form.get("description", "").strip()
        priority = form.get("priority", "medium")
        due_raw = form.get("due_date", "").strip()
        errors = []

        if not title:
            errors.append("Give the task a title.")
        elif len(title) > TITLE_MAX:
            errors.append(f"Keep the title under {TITLE_MAX} characters.")
        if len(description) > DESCRIPTION_MAX:
            errors.append(f"Keep notes under {DESCRIPTION_MAX} characters.")
        if priority not in PRIORITIES:
            errors.append("Choose low, medium or high priority.")
        due = None
        if due_raw:
            try:
                due = date.fromisoformat(due_raw).isoformat()
            except ValueError:
                errors.append("Enter the due date as YYYY-MM-DD.")
        return {"title": title, "description": description,
                "priority": priority, "due_date": due}, errors

    def get_task_or_404(task_id):
        row = db.get_db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    def back_to_list():
        """Return to the list, keeping whichever filters were active."""
        args = {k: request.form.get(k) for k in ("status", "priority", "sort")
                if request.form.get(k)}
        return redirect(url_for("index", **args))

    # ---- routes ----------------------------------------------------------
    @app.get("/")
    def index():
        status = request.args.get("status", "all")
        priority = request.args.get("priority", "all")
        sort = request.args.get("sort", "priority")
        if status not in STATUSES:
            status = "all"
        if priority not in PRIORITIES and priority != "all":
            priority = "all"
        if sort not in SORTS:
            sort = "priority"

        clauses, params = [], []
        if status != "all":
            clauses.append("completed = ?")
            params.append(1 if status == "completed" else 0)
        if priority != "all":
            clauses.append("priority = ?")
            params.append(priority)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        conn = db.get_db()
        # SORTS values are fixed strings from the dict above, never user input.
        tasks = conn.execute(f"SELECT * FROM tasks {where} ORDER BY {SORTS[sort]}", params).fetchall()
        counts = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(completed = 0), 0) AS active, "
            "COALESCE(SUM(completed = 1), 0) AS done FROM tasks").fetchone()
        return render_template("index.html", tasks=tasks, counts=counts,
                               status=status, priority=priority, sort=sort,
                               today=date.today().isoformat(), priorities=PRIORITIES)

    @app.post("/tasks")
    def create_task():
        data, errors = parse_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            conn = db.get_db()
            conn.execute(
                "INSERT INTO tasks (title, description, priority, due_date) VALUES (?, ?, ?, ?)",
                (data["title"], data["description"], data["priority"], data["due_date"]))
            conn.commit()
            flash("Task added.", "success")
        return back_to_list()

    @app.route("/tasks/<int:task_id>/edit", methods=("GET", "POST"))
    def edit_task(task_id):
        task = get_task_or_404(task_id)
        if request.method == "POST":
            data, errors = parse_form(request.form)
            if errors:
                for e in errors:
                    flash(e, "error")
                task = {**dict(task), **data}
            else:
                conn = db.get_db()
                conn.execute(
                    "UPDATE tasks SET title=?, description=?, priority=?, due_date=? WHERE id=?",
                    (data["title"], data["description"], data["priority"], data["due_date"], task_id))
                conn.commit()
                flash("Changes saved.", "success")
                return redirect(url_for("index"))
        return render_template("edit.html", task=task, priorities=PRIORITIES)

    @app.post("/tasks/<int:task_id>/toggle")
    def toggle_task(task_id):
        task = get_task_or_404(task_id)
        done = 0 if task["completed"] else 1
        conn = db.get_db()
        conn.execute("UPDATE tasks SET completed=?, completed_at=? WHERE id=?",
                     (done, datetime.now().isoformat(timespec="seconds") if done else None, task_id))
        conn.commit()
        return back_to_list()

    @app.post("/tasks/<int:task_id>/delete")
    def delete_task(task_id):
        get_task_or_404(task_id)
        conn = db.get_db()
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        flash("Task deleted.", "success")
        return back_to_list()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
