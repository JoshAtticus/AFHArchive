from flask import request
from app import socketio


@socketio.on('connect', namespace='/autoreviewer')
def autoreviewer_connect():
    return True


@socketio.on('disconnect', namespace='/autoreviewer')
def autoreviewer_disconnect():
    return


@socketio.on('ping', namespace='/autoreviewer')
def autoreviewer_ping():
    socketio.emit('pong', {}, namespace='/autoreviewer', to=request.sid)
