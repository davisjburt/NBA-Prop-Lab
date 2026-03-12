from flask import Flask
from app.models.models import db

def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    db.init_app(app)

    from app.routes.players import players_bp
    from app.routes.props import props_bp
    app.register_blueprint(players_bp)
    app.register_blueprint(props_bp)

    with app.app_context():
        db.create_all()

    return app
