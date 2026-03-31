web: gunicorn "app:create_app()" --bind 0.0.0.0:$PORT
release: python -c "from app import create_app; app = create_app(); app.app_context().push()"
