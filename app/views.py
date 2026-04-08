# -*- coding: utf-8 -*-
from flask import Blueprint, render_template
from flask_login import login_required
from flask_socketio import emit
from app import socketio
from app.swarm import SwarmManager, MACDAgent, RSIAgent
from app.alerts import alert_manager

main_bp = Blueprint('main', __name__)

# Initialize SwarmManager
swarm = SwarmManager(
    symbols=['AAPL', 'GOOG', 'MSFT'],
    agents=[MACDAgent(), RSIAgent()]
)

@main_bp.route('/')
@login_required
def index():
    return render_template('index.html', symbols=swarm.symbols)

@socketio.on('connect')
def handle_connect():
    emit('init', {'symbols': swarm.symbols, 'prices': {}, 'metrics': {}})

@socketio.on('start')
def start_updates():
    def background():
        while True:
            data = swarm.advance()
            alert_manager(data['metrics'])
            socketio.emit('update', data)
            socketio.sleep(1)
    socketio.start_background_task(background)
