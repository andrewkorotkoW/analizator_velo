import os
import tempfile

# Устанавливаем ANAL_VELO_DB_PATH ДО того, как что-либо в тестовой сессии
# впервые импортирует app.storage / app.main. app.main создаёт модуль-уровневый
# `app = create_app()` при импорте, что вызывает init_db() и коснётся файла
# по умолчанию (data.db в корне репозитория), если не перенаправить путь заранее.
_SESSION_TMP_DIR = tempfile.mkdtemp(prefix="anal_velo_test_")
os.environ.setdefault(
    "ANAL_VELO_DB_PATH", os.path.join(_SESSION_TMP_DIR, "session_default.db")
)
