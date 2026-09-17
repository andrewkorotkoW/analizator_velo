import io
import os
import zipfile
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import Workout
from app.ocr import recognize_text
from app.parser import ParseError, parse_file
from app.photo_parse import parse_ocr_text
from app.photos import (
    PhotoError,
    finalize_photo,
    resolve_permanent_photo,
    save_temp_photo,
    temp_photo_path,
)
from app.recommendations import (
    build_recommendations,
    hr_zone_distribution,
    resolve_max_hr,
    weekly_volume,
)
from app.storage import (
    create_user,
    delete_workout,
    get_user_by_email,
    get_user_by_id,
    get_workouts,
    has_legacy_workouts,
    init_db,
    migrate_email_to_user,
    save_workouts,
    update_user_profile,
)


def _parse_optional_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_optional_float(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _coerce_float(value):
    """Как _parse_optional_float, но принимает и уже готовые числа (для JSON-тела)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("ANAL_VELO_SECRET_KEY", "dev-secret-key-change-me")
    init_db()

    def get_current_user():
        user_id = session.get("user_id")
        if user_id is None:
            return None
        return get_user_by_id(user_id)

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Требуется вход"}), 401
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    @app.get("/")
    @login_required
    def dashboard():
        user = get_current_user()
        return render_template("dashboard.html", user=user)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        error = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            password2 = request.form.get("password2") or ""
            name = (request.form.get("name") or "").strip() or None
            age = _parse_optional_int(request.form.get("age"))
            max_hr = _parse_optional_int(request.form.get("max_hr"))
            weight = _parse_optional_float(request.form.get("weight"))

            if not email or not password:
                error = "Укажите email и пароль"
            elif password != password2:
                error = "Пароли не совпадают"
            elif get_user_by_email(email) is not None:
                error = "Пользователь с таким email уже зарегистрирован"

            if error is None:
                user = create_user(
                    email=email,
                    password_hash=generate_password_hash(password),
                    name=name,
                    age=age,
                    max_hr=max_hr,
                    weight=weight,
                )
                migrate_email_to_user(email, user.id)
                session["user_id"] = user.id
                return redirect(url_for("dashboard"))

        return render_template("register.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        hint = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            user = get_user_by_email(email)

            if user is not None and check_password_hash(user.password_hash, password):
                session["user_id"] = user.id
                migrate_email_to_user(email, user.id)
                return redirect(url_for("dashboard"))

            if user is None and email and has_legacy_workouts(email):
                hint = (
                    f"Для {email} есть сохранённые тренировки, но пароль ещё не задан — "
                    "зарегистрируйтесь с этим email, чтобы получить к ним доступ."
                )
            else:
                error = "Неверный email или пароль"

        return render_template("login.html", error=error, hint=hint)

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        user = get_current_user()
        saved = False
        if request.method == "POST":
            name = (request.form.get("name") or "").strip() or None
            age = _parse_optional_int(request.form.get("age"))
            max_hr = _parse_optional_int(request.form.get("max_hr"))
            weight = _parse_optional_float(request.form.get("weight"))
            user = update_user_profile(user.id, name=name, age=age, max_hr=max_hr, weight=weight)
            saved = True

        return render_template("profile.html", user=user, saved=saved)

    @app.post("/api/workouts/upload")
    @login_required
    def upload_workouts():
        user = get_current_user()

        uploaded_files = [f for f in request.files.getlist("file") if f and f.filename]
        if not uploaded_files:
            return jsonify({"error": "Не передан файл с тренировками (поле 'file')"}), 400

        workouts = []
        errors = []

        def parse_into(filename, content):
            try:
                workouts.extend(parse_file(filename, content, user.email))
            except ParseError as e:
                errors.append({"filename": filename, "message": str(e)})

        for uploaded_file in uploaded_files:
            filename = uploaded_file.filename
            raw = uploaded_file.read()

            if filename.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        for member in archive.namelist():
                            if member.endswith("/"):
                                continue
                            parse_into(member, archive.read(member))
                except zipfile.BadZipFile:
                    errors.append({"filename": filename, "message": "Повреждённый ZIP-архив"})
                continue

            parse_into(filename, raw)

        if not workouts:
            return jsonify({"error": "Не удалось разобрать ни один файл", "errors": errors}), 400

        result = save_workouts(user.email, workouts, user_id=user.id)
        return (
            jsonify(
                {
                    "saved": result["saved"],
                    "duplicates": result["duplicates"],
                    "errors": errors,
                }
            ),
            201,
        )

    @app.get("/api/workouts")
    @login_required
    def list_workouts():
        user = get_current_user()
        workouts = get_workouts(user_id=user.id)
        return jsonify([w.to_dict() for w in workouts])

    @app.post("/api/workouts/photo")
    @login_required
    def upload_workout_photo():
        """Загружает фото тренировки, прогоняет OCR и возвращает распознанные поля
        для подтверждения. Тренировка на этом шаге ещё не сохраняется."""
        uploaded = request.files.get("photo")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Не передано фото (поле 'photo')"}), 400

        content = uploaded.read()
        try:
            token = save_temp_photo(content, uploaded.filename)
        except PhotoError as e:
            return jsonify({"error": str(e)}), 400

        with open(temp_photo_path(token), "rb") as f:
            image_bytes = f.read()

        ocr_result = recognize_text(image_bytes)
        parsed = parse_ocr_text(ocr_result["text"])

        return (
            jsonify(
                {
                    "photo_token": token,
                    "photo_url": url_for("serve_temp_photo", token=token),
                    "ocr_backend": ocr_result["backend"],
                    "ocr_message": ocr_result["message"],
                    "fields": {
                        "date": parsed["date"],
                        "distance_km": parsed["distance_km"],
                        "duration_min": parsed["duration_min"],
                        "avg_speed_kmh": parsed["avg_speed_kmh"],
                        "avg_hr": parsed["avg_hr"],
                        "elevation_gain_m": parsed["elevation_gain_m"],
                    },
                    "confidence": parsed["confidence"],
                    "fragments": parsed["fragments"],
                }
            ),
            201,
        )

    @app.get("/api/photos/tmp/<token>")
    @login_required
    def serve_temp_photo(token):
        path = temp_photo_path(token)
        if not path:
            return jsonify({"error": "Фото не найдено"}), 404
        return send_file(path, mimetype="image/jpeg")

    @app.get("/api/photos/<path:relpath>")
    @login_required
    def serve_user_photo(relpath):
        user = get_current_user()
        resolved = resolve_permanent_photo(relpath)
        if not resolved or resolved[0] != user.id:
            return jsonify({"error": "Фото не найдено"}), 404
        return send_file(resolved[1], mimetype="image/jpeg")

    @app.post("/api/workouts/photo/confirm")
    @login_required
    def confirm_workout_photo():
        """Сохраняет тренировку по подтверждённым пользователем полям и токену фото."""
        user = get_current_user()
        data = request.get_json(silent=True) or request.form

        token = (data.get("photo_token") or "").strip()
        if not token:
            return jsonify({"error": "Не передан photo_token"}), 400

        date = (data.get("date") or "").strip()
        distance_km = _coerce_float(data.get("distance_km"))
        duration_min = _coerce_float(data.get("duration_min"))
        avg_speed_kmh = _coerce_float(data.get("avg_speed_kmh"))
        avg_hr = _coerce_float(data.get("avg_hr"))
        elevation_gain_m = _coerce_float(data.get("elevation_gain_m"))

        if not date or distance_km is None or duration_min is None:
            return jsonify({"error": "Укажите дату, дистанцию и время тренировки"}), 400

        try:
            relative_photo_path = finalize_photo(token, user.id)
        except PhotoError as e:
            return jsonify({"error": str(e)}), 400

        workout = Workout(
            user_email=user.email,
            date=date,
            distance_km=distance_km,
            duration_min=duration_min,
            avg_speed_kmh=avg_speed_kmh,
            avg_hr=avg_hr,
            elevation_gain_m=elevation_gain_m,
            source="photo",
            photo_path=relative_photo_path,
        )
        result = save_workouts(user.email, [workout], user_id=user.id)
        return jsonify({"saved": result["saved"], "duplicates": result["duplicates"]}), 201

    @app.delete("/api/workouts/<int:workout_id>")
    @login_required
    def delete_workout_route(workout_id):
        user = get_current_user()
        if not delete_workout(user.id, workout_id):
            return jsonify({"error": "Тренировка не найдена"}), 404
        return jsonify({"deleted": True})

    @app.get("/api/recommendations")
    @login_required
    def recommendations():
        user = get_current_user()
        workouts = get_workouts(user_id=user.id)
        max_hr = resolve_max_hr(user.max_hr, user.age)
        return jsonify(
            {
                "recommendations": build_recommendations(workouts, max_hr=max_hr),
                "weekly": weekly_volume(workouts),
                "hr_zones": hr_zone_distribution(workouts, max_hr),
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
