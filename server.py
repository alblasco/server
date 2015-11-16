#!/usr/bin/env python3
"""
Usage:
    server.py [--nodb | --db TYPE]

Options:
    --nodb      Don't use a database (Use a mock.Mock). Caution: Will break things.
    --db TYPE   Use TYPE database driver [default: QMYSQL]
"""

import asyncio

import logging
from logging import handlers
import signal
import socket

from passwords import DB_SERVER, DB_PORT, DB_LOGIN, DB_PASSWORD, DB_NAME
from server.game_service import GameService
from server.matchmaker import MatchmakerQueue
from server.player_service import PlayerService
import config
import server

if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    try:
        def signal_handler(signal, frame):
            logger.info("Received signal, shutting down")
            if not done.done():
                done.set_result(0)

        loop = asyncio.get_event_loop()
        done = asyncio.Future()

        from docopt import docopt
        args = docopt(__doc__, version='FAF Server')

        rootlogger = logging.getLogger("")
        logHandler = handlers.RotatingFileHandler(config.LOG_PATH + "server.log", backupCount=1024, maxBytes=16777216)
        logFormatter = logging.Formatter('%(asctime)s %(levelname)-8s %(name)-20s %(message)s')
        logHandler.setFormatter(logFormatter)
        rootlogger.addHandler(logHandler)
        rootlogger.setLevel(config.LOG_LEVEL)

        # Make sure we can shutdown gracefully
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        pool_fut = asyncio.async(server.db.connect(host=DB_SERVER,
                                                   port=int(DB_PORT),
                                                   user=DB_LOGIN,
                                                   password=DB_PASSWORD,
                                                   maxsize=10,
                                                   db=DB_NAME,
                                                   loop=loop))
        db_pool = loop.run_until_complete(pool_fut)

        players_online = PlayerService(db_pool)
        games = GameService(players_online)
        matchmaker_queue = MatchmakerQueue('ladder1v1', players_online, games)
        players_online.ladder_queue = matchmaker_queue

        ctrl_server = loop.run_until_complete(server.run_control_server(loop, players_online, games))

        lobby_server = loop.run_until_complete(
            server.run_lobby_server(('', 8001),
                                    players_online,
                                    games,
                                    loop)
        )
        for sock in lobby_server.sockets:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        nat_packet_server, game_server = \
            server.run_game_server(('', 8000),
                                   players_online,
                                   games,
                                   loop)
        game_server = loop.run_until_complete(game_server)

        loop.run_until_complete(done)
        loop.close()

    except Exception as ex:
        logger.exception("Failure booting server {}".format(ex))
