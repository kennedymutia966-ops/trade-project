import functools
import re
from datetime import date

import mysql.connector
from flask import Flask, flash, redirect, render_template, request, session, url_for
from markupsafe import escape
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "change-this-to-any-random-text"

# Change these to match your MySQL setup (XAMPP default: user root, empty password)
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "sims_db",
}

DEFAULT_YEAR = "2026/2027"
ADMIN_REG = ("Admin", "Registrar")
ADMIN_LEC = ("Admin", "Lecturer")
ATTENDANCE_STATES = ("Present", "Absent", "Late", "Excused")


# ------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------
def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def query(sql, params=(), one=False):
    """Run a SELECT and return a list of dicts (or one dict if one=True)."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()
        db.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=(), many=False):
    """Run an INSERT/UPDATE/DELETE and return the number of rows changed."""
    db = get_db()
    cur = db.cursor()
    try:
        if many:
            cur.executemany(sql, params)
        else:
            cur.execute(sql, params)
        db.commit()
        return cur.rowcount
    finally:
        cur.close()
        db.close()


def clean(value):
    """Turn empty form fields into NULL so UNIQUE columns (like email) don't clash."""
    value = (value or "").strip()
    return value if value else None


def grade_for(total):
    if total >= 70:
        return "Distinction"
    if total >= 60:
        return "Credit"
    if total >= 50:
        return "Pass"
    return "Fail"


def parse_mark(value, maximum):
    """Empty -> None (no mark yet). Invalid or out of range -> False."""
    value = (value or "").strip()
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return False
    return number if 0 <= number <= maximum else False


def parse_day(text):
    try:
        return date.fromisoformat(text).isoformat()
    except (TypeError, ValueError):
        return date.today().isoformat()


def allowed_units():
    """Lecturers only see the units allocated to them; Admin sees all."""
    if session.get("role") == "Lecturer" and session.get("lecturer_id"):
        return query(
            """SELECT DISTINCT u.unit_id, u.unit_code, u.unit_name
               FROM units u JOIN unit_allocations a ON a.unit_id = u.unit_id
               WHERE a.lecturer_id = %s ORDER BY u.unit_code""",
            (session["lecturer_id"],),
        )
    return query("SELECT unit_id, unit_code, unit_name FROM units ORDER BY unit_code")


# ------------------------------------------------------------
# Login protection
# ------------------------------------------------------------
def login_required(roles=None):
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login", next=request.path))
            if roles and session.get("role") not in roles:
                flash("You do not have permission to open that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapper
    return decorator


@app.errorhandler(mysql.connector.Error)
def database_error(err):
    return (
        "<h2>Database problem</h2>"
        "<p>Check that MySQL is running in XAMPP and that DB_CONFIG in app.py is correct.</p>"
        "<p>" + str(escape(err)) + "</p>",
        500,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query(
            "SELECT * FROM users WHERE username = %s AND is_active = 1",
            (username,), one=True,
        )
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["lecturer_id"] = user["lecturer_id"]
            nxt = request.args.get("next", "")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("dashboard")
            return redirect(nxt)
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------
@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required()
def dashboard():
    tables = [
        ("Students", "students"), ("Courses", "courses"), ("Units", "units"),
        ("Lecturers", "lecturers"), ("Enrollments", "enrollments"),
        ("Grades entered", "grades"), ("Attendance records", "attendance"),
    ]
    stats = [(label, query(f"SELECT COUNT(*) AS n FROM {table}", one=True)["n"])
             for label, table in tables]
    return render_template("dashboard.html", stats=stats)


# ------------------------------------------------------------
# Students
# ------------------------------------------------------------
@app.route("/students", methods=["GET", "POST"])
@login_required(ADMIN_REG)
def students():
    if request.method == "POST":
        try:
            execute(
                """INSERT INTO students
                   (admission_no, first_name, last_name, gender, date_of_birth,
                    phone, email, course_id, date_enrolled)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    request.form["admission_no"].strip(),
                    request.form["first_name"].strip(),
                    request.form["last_name"].strip(),
                    request.form["gender"],
                    clean(request.form.get("date_of_birth")),
                    clean(request.form.get("phone")),
                    clean(request.form.get("email")),
                    request.form["course_id"],
                    request.form["date_enrolled"],
                ),
            )
            flash("Student added successfully.", "success")
        except mysql.connector.Error as err:
            flash(f"Could not save student: {err.msg}", "error")
        return redirect(url_for("students"))

    search = request.args.get("q", "").strip()
    sql = """SELECT s.*, c.course_name FROM students s
             JOIN courses c ON c.course_id = s.course_id"""
    params = ()
    if search:
        sql += " WHERE s.admission_no LIKE %s OR s.first_name LIKE %s OR s.last_name LIKE %s"
        params = (f"%{search}%",) * 3
    sql += " ORDER BY s.last_name, s.first_name"
    student_list = query(sql, params)
    courses = query("SELECT course_id, course_name FROM courses ORDER BY course_name")
    return render_template("students.html", students=student_list, courses=courses, search=search)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required(ADMIN_REG)
def delete_student(student_id):
    try:
        execute("DELETE FROM students WHERE student_id = %s", (student_id,))
        flash("Student deleted.", "success")
    except mysql.connector.Error as err:
        flash(f"Could not delete: {err.msg}", "error")
    return redirect(url_for("students"))


# ------------------------------------------------------------
# Enrollments
# ------------------------------------------------------------
@app.route("/enrollments", methods=["GET", "POST"])
@login_required(ADMIN_REG)
def enrollments():
    if request.method == "POST":
        action = request.form.get("action")
        year = request.form.get("academic_year", "").strip()
        if not re.fullmatch(r"\d{4}/\d{4}", year):
            flash("Academic year must look like 2026/2027.", "error")
            return redirect(url_for("enrollments"))
        try:
            if action == "single":
                student_id = request.form["student_id"]
                unit_id = request.form["unit_id"]
                same_course = query(
                    """SELECT 1 AS ok FROM students s JOIN units u ON u.course_id = s.course_id
                       WHERE s.student_id = %s AND u.unit_id = %s""",
                    (student_id, unit_id), one=True,
                )
                if not same_course:
                    flash("That unit does not belong to the student's course.", "error")
                else:
                    execute(
                        """INSERT INTO enrollments (student_id, unit_id, academic_year, semester)
                           SELECT %s, unit_id, %s, semester FROM units WHERE unit_id = %s""",
                        (student_id, year, unit_id),
                    )
                    flash("Student enrolled.", "success")
            elif action == "course":
                added = execute(
                    """INSERT IGNORE INTO enrollments (student_id, unit_id, academic_year, semester)
                       SELECT s.student_id, u.unit_id, %s, u.semester
                       FROM students s JOIN units u ON u.course_id = s.course_id
                       WHERE s.course_id = %s AND s.status = 'Active'""",
                    (year, request.form["course_id"]),
                )
                flash(f"{added} enrollment(s) added.", "success")
        except mysql.connector.Error as err:
            if err.errno == 1062:
                flash("That student is already enrolled in that unit for this year.", "error")
            else:
                flash(f"Could not enroll: {err.msg}", "error")
        return redirect(url_for("enrollments", year=year))

    year = request.args.get("year", DEFAULT_YEAR).strip()
    enrolled = query(
        """SELECT e.enrollment_id, s.admission_no,
                  CONCAT(s.first_name, ' ', s.last_name) AS student_name,
                  u.unit_code, u.unit_name, e.academic_year, e.semester
           FROM enrollments e
           JOIN students s ON s.student_id = e.student_id
           JOIN units u ON u.unit_id = e.unit_id
           WHERE e.academic_year = %s
           ORDER BY s.last_name, s.first_name, u.unit_code""",
        (year,),
    )
    return render_template(
        "enrollments.html",
        enrolled=enrolled, year=year, default_year=DEFAULT_YEAR,
        students=query("""SELECT student_id, admission_no,
                                 CONCAT(first_name, ' ', last_name) AS name
                          FROM students ORDER BY first_name, last_name"""),
        units=query("""SELECT u.unit_id, u.unit_code, u.unit_name, c.course_name
                       FROM units u JOIN courses c ON c.course_id = u.course_id
                       ORDER BY u.unit_code"""),
        courses=query("SELECT course_id, course_name FROM courses ORDER BY course_name"),
    )


@app.route("/enrollments/<int:enrollment_id>/delete", methods=["POST"])
@login_required(ADMIN_REG)
def delete_enrollment(enrollment_id):
    try:
        execute("DELETE FROM enrollments WHERE enrollment_id = %s", (enrollment_id,))
        flash("Enrollment removed (and its marks, if any).", "success")
    except mysql.connector.Error as err:
        flash(f"Could not remove: {err.msg}", "error")
    return redirect(url_for("enrollments", year=request.form.get("year", DEFAULT_YEAR)))


# ------------------------------------------------------------
# Grades entry
# ------------------------------------------------------------
@app.route("/grades", methods=["GET", "POST"])
@login_required(ADMIN_LEC)
def grades():
    units = allowed_units()
    allowed_ids = {u["unit_id"] for u in units}
    unit_id = request.values.get("unit_id", type=int)
    year = request.values.get("academic_year", DEFAULT_YEAR).strip()

    if unit_id is not None and unit_id not in allowed_ids:
        flash("You are not allocated to that unit.", "error")
        unit_id = None

    rows = []
    if unit_id:
        rows = query(
            """SELECT e.enrollment_id, s.admission_no,
                      CONCAT(s.first_name, ' ', s.last_name) AS student_name,
                      g.cat_marks, g.exam_marks, g.total_marks, g.grade_letter
               FROM enrollments e
               JOIN students s ON s.student_id = e.student_id
               LEFT JOIN grades g ON g.enrollment_id = e.enrollment_id
               WHERE e.unit_id = %s AND e.academic_year = %s
               ORDER BY s.last_name, s.first_name""",
            (unit_id, year),
        )
        if request.method == "POST":
            to_save, invalid = [], []
            for r in rows:
                cat = parse_mark(request.form.get(f"cat_{r['enrollment_id']}"), 30)
                exam = parse_mark(request.form.get(f"exam_{r['enrollment_id']}"), 70)
                if cat is False or exam is False:
                    invalid.append(r["student_name"])
                else:
                    to_save.append((r["enrollment_id"], cat, exam))
            if to_save:
                execute(
                    """INSERT INTO grades (enrollment_id, cat_marks, exam_marks)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           cat_marks = VALUES(cat_marks), exam_marks = VALUES(exam_marks)""",
                    to_save, many=True,
                )
                flash(f"Marks saved for {len(to_save)} student(s).", "success")
            if invalid:
                flash("Not saved (CAT must be 0-30, exam 0-70): " + ", ".join(invalid), "error")
            return redirect(url_for("grades", unit_id=unit_id, academic_year=year))

    return render_template("grades.html", units=units, unit_id=unit_id, year=year, rows=rows)


# ------------------------------------------------------------
# Attendance (digital roll call)
# ------------------------------------------------------------
@app.route("/attendance", methods=["GET", "POST"])
@login_required(ADMIN_LEC)
def attendance():
    units = allowed_units()
    allowed_ids = {u["unit_id"] for u in units}
    unit_id = request.values.get("unit_id", type=int)
    day = parse_day(request.values.get("attendance_date"))

    if unit_id is not None and unit_id not in allowed_ids:
        flash("You are not allocated to that unit.", "error")
        unit_id = None

    rows = []
    if unit_id:
        rows = query(
            """SELECT s.student_id, s.admission_no,
                      CONCAT(s.first_name, ' ', s.last_name) AS student_name,
                      a.status,
                      (SELECT COUNT(*) FROM attendance x
                        WHERE x.student_id = s.student_id AND x.unit_id = %s
                          AND x.status IN ('Present', 'Late')) AS attended,
                      (SELECT COUNT(*) FROM attendance x
                        WHERE x.student_id = s.student_id AND x.unit_id = %s) AS total_days
               FROM students s
               JOIN (SELECT DISTINCT student_id FROM enrollments WHERE unit_id = %s) en
                    ON en.student_id = s.student_id
               LEFT JOIN attendance a
                    ON a.student_id = s.student_id AND a.unit_id = %s AND a.attendance_date = %s
               ORDER BY s.last_name, s.first_name""",
            (unit_id, unit_id, unit_id, unit_id, day),
        )
        if request.method == "POST":
            to_save = []
            for r in rows:
                status = request.form.get(f"status_{r['student_id']}")
                if status in ATTENDANCE_STATES:
                    to_save.append((r["student_id"], unit_id, day, status, session.get("lecturer_id")))
            if to_save:
                execute(
                    """INSERT INTO attendance (student_id, unit_id, attendance_date, status, recorded_by)
                       VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           status = VALUES(status), recorded_by = VALUES(recorded_by)""",
                    to_save, many=True,
                )
                flash(f"Attendance saved for {len(to_save)} student(s) on {day}.", "success")
            return redirect(url_for("attendance", unit_id=unit_id, attendance_date=day))

    return render_template("attendance.html", units=units, unit_id=unit_id, day=day,
                           rows=rows, states=ATTENDANCE_STATES)


# ------------------------------------------------------------
# Transcript
# ------------------------------------------------------------
@app.route("/transcript")
@login_required()
def transcript():
    student_id = request.args.get("student_id", type=int)
    student, rows, summary = None, [], None
    if student_id:
        rows = query(
            "SELECT * FROM v_transcript WHERE student_id = %s ORDER BY academic_year, semester, unit_code",
            (student_id,),
        )
        if rows:
            student = rows[0]
        else:
            student = query(
                """SELECT s.admission_no, CONCAT(s.first_name, ' ', s.last_name) AS student_name,
                          c.course_name
                   FROM students s JOIN courses c ON c.course_id = s.course_id
                   WHERE s.student_id = %s""",
                (student_id,), one=True,
            )
        totals = [float(r["total_marks"]) for r in rows if r["total_marks"] is not None]
        if totals:
            average = sum(totals) / len(totals)
            summary = {
                "units": len(totals),
                "average": round(average, 1),
                "grade": grade_for(average),
                "passed": sum(1 for t in totals if t >= 50),
            }
    student_list = query("""SELECT student_id, admission_no,
                                   CONCAT(first_name, ' ', last_name) AS name
                            FROM students ORDER BY first_name, last_name""")
    return render_template("transcript.html", student_list=student_list, student_id=student_id,
                           student=student, rows=rows, summary=summary, today=date.today().isoformat())


if __name__ == "__main__":
    app.run(debug=True)
