import io
import zipfile

from flask import Flask, jsonify, render_template, request

from app.parser import ParseError, parse_file
from app.recommendations import (
    build_recommendations,
    hr_zone_distribution,
    resolve_max_hr,
    weekly_volume,
)
from app.storage import get_workouts, init_db, save_workouts

# Профиль пользователя (и его max_hr) появится в задаче логина — до тех пор используем дефолт.
DEFAULT_USER_MAX_HR = None


def create_app() -> Flask:
    app = Flask(__name__)
    init_db()

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.post("/api/workouts/upload")
    def upload_workouts():
        user_email = request.form.get("user_email")
        if not user_email:
            return jsonify({"error": "Не передан user_email"}), 400

        uploaded_files = [f for f in request.files.getlist("file") if f and f.filename]
        if not uploaded_files:
            return jsonify({"error": "Не передан файл с тренировками (поле 'file')"}), 400

        workouts = []
        errors = []

        def parse_into(filename, content):
            try:
                workouts.extend(parse_file(filename, content, user_email))
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

        result = save_workouts(user_email, workouts)
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
    def list_workouts():
        user_email = request.args.get("user_email")
        if not user_email:
            return jsonify({"error": "Не передан user_email"}), 400

        workouts = get_workouts(user_email)
        return jsonify([w.to_dict() for w in workouts])

    @app.get("/api/recommendations")
    def recommendations():
        user_email = request.args.get("user_email")
        if not user_email:
            return jsonify({"error": "Не передан user_email"}), 400

        workouts = get_workouts(user_email)
        max_hr = resolve_max_hr(DEFAULT_USER_MAX_HR)
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
