from flask import Flask, jsonify, render_template, request

from app.parser import CsvParseError, parse_csv
from app.recommendations import build_recommendation
from app.storage import get_workouts, init_db, save_workouts


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

        uploaded_file = request.files.get("file")
        if uploaded_file is None or uploaded_file.filename == "":
            return jsonify({"error": "Не передан CSV-файл (поле 'file')"}), 400

        try:
            content = uploaded_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return jsonify({"error": "Файл должен быть в кодировке UTF-8"}), 400

        try:
            workouts = parse_csv(content, user_email)
        except CsvParseError as e:
            return jsonify({"error": str(e)}), 400

        saved = save_workouts(user_email, workouts)
        return jsonify({"saved": saved}), 201

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
        return jsonify({"recommendation": build_recommendation(workouts)})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
