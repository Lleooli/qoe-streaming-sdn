#!/usr/bin/env python3
"""
Servidor HTTP do conteudo DASH (threaded, com log de acessos em arquivo).

Uso: dash_server.py --dir video/dash --port 8080 --log results/server.log
"""

import argparse
import os
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler


class LoggingHandler(SimpleHTTPRequestHandler):
    logfile = None

    def log_message(self, fmt, *fmt_args):
        if self.logfile:
            self.logfile.write('%s - %s\n' % (self.address_string(),
                                              fmt % fmt_args))
            self.logfile.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--log', default=None)
    args = ap.parse_args()

    if args.log:
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        LoggingHandler.logfile = open(args.log, 'a')

    handler = partial(LoggingHandler, directory=args.dir)
    srv = ThreadingHTTPServer(('0.0.0.0', args.port), handler)
    print(f'Servindo {args.dir} na porta {args.port}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
