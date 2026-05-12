"""Blueprints Flask. Cada modulo expone un Blueprint en la variable `bp`.

`register_blueprints(app)` los registra todos de una vez."""

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from . import pages, connection, motion, vision, follow, sensor, autoroute, agent, gestures, faces, map_ai

    app.register_blueprint(pages.bp)
    app.register_blueprint(connection.bp)
    app.register_blueprint(motion.bp)
    app.register_blueprint(vision.bp)
    app.register_blueprint(follow.bp)
    app.register_blueprint(sensor.bp)
    app.register_blueprint(autoroute.bp)
    app.register_blueprint(agent.bp)
    app.register_blueprint(gestures.bp)
    app.register_blueprint(faces.bp)
    app.register_blueprint(map_ai.bp)
