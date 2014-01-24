# -*- coding: utf-8 -*-
import pprint
import sys
import logging
import time
import socket
from tornado.ioloop import IOLoop
from tornado.iostream import StreamClosedError
from tornado.tcpserver import TCPServer
from tornado import autoreload
import Utils
import BaseThreadedModule
from Decorators import ModuleDocstringParser

class TornadoTcpServer(TCPServer):

    def __init__(self, io_loop=None, ssl_options=None, gp_module=False, **kwargs):
        TCPServer.__init__(self, io_loop=io_loop, ssl_options=ssl_options, **kwargs)
        self.gp_module = gp_module

    def handle_stream(self, stream, address):
        ConnectionHandler(stream, address, self.gp_module)

class ConnectionHandler(object):

    stream_set = set([])

    def __init__(self, stream, address, gp_module):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.gp_module = gp_module
        self.is_open = True
        self.stream = stream
        self.address = address
        self.stream.set_close_callback(self._on_close)
        if not self.stream.closed():
            self.stream.read_until_regex(b'\r?\n', self._on_read_line)

    def _on_read_line(self, data):
        (host, port) = self.address
        data = data.strip()
        if data != "":
            self.gp_module.sendEvent(Utils.getDefaultEventDict({"received_from": host, "data": data}, caller_class_name="TcpServerTornado"))
        try:
            self.stream.read_until_regex(b'\r?\n', self._on_read_line)
        except StreamClosedError:
            pass
        except:
            etype, evalue, etb = sys.exc_info()
            self.logger.error("%sFailed to read from stream. Exception: %s, Error: %s.%s" % (Utils.AnsiColors.FAIL, etype, evalue, Utils.AnsiColors.ENDC))

    def _on_close(self):
        self.stream.close()

@ModuleDocstringParser
class TcpServerTornado(BaseThreadedModule.BaseThreadedModule):
    """
    Reads data from tcp socket and sends it to its output queues.
    Should be the best choice perfomancewise if you are on Linux.

    Configuration example:

    - module: TcpServerTornado
      interface: localhost             # <default: ''; type: string; is: optional>
      port: 5050                       # <default: 5151; type: integer; is: optional>
      timeout: 5                       # <default: None; type: None||integer; is: optional>
      tls: False                       # <default: False; type: boolean; is: optional>
      key: /path/to/cert.key           # <default: False; type: boolean||string; is: required if tls is True else optional>
      cert: /path/to/cert.crt          # <default: False; type: boolean||string; is: required if tls is True else optional>
      receivers:
        - NextModule
    """

    module_type = "input"
    """Set module type"""

    can_run_parallel = False

    def configure(self, configuration):
        # Call parent configure method
        BaseThreadedModule.BaseThreadedModule.configure(self, configuration)
        self.server = False

    def run(self):
        if not self.receivers:
            self.logger.error("%sWill not start module %s since no receivers are set.%s" % (Utils.AnsiColors.FAIL, self.__class__.__name__, Utils.AnsiColors.ENDC))
            return
        try:
            ssl_options = None
            if self.getConfigurationValue("tls"):
                ssl_options = { 'certfile': self.getConfigurationValue("cert"),
                                'keyfile': self.getConfigurationValue("key")}
            self.server = TornadoTcpServer(ssl_options=ssl_options, gp_module=self)
            self.server.listen(self.getConfigurationValue("port"), self.getConfigurationValue("interface"))
            for fd, server_socket in self.server._sockets.iteritems():
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except:
            etype, evalue, etb = sys.exc_info()
            self.logger.error("%sCould not listen on %s:%s. Exception: %s, Error: %s.%s" % (Utils.AnsiColors.FAIL, self.getConfigurationValue("interface"),
                                                                                       self.getConfigurationValue("port"), etype, evalue, Utils.AnsiColors.ENDC))
            self.gp.shutDown()
            return
        autoreload.add_reload_hook(self.shutDown)
        return
        ioloop = IOLoop.instance()
        ioloop.make_current()
        try:
            ioloop.start()
        except ValueError:
            # Ignore errors like "ValueError: I/O operation on closed kqueue fd". These might be thrown during a reload.
            pass

    def shutDown(self, silent):
        # Call parent shutDown method
        BaseThreadedModule.BaseThreadedModule.shutDown(self, silent)
        if self.server:
            self.server.stop()
            # Give os time to free the socket. Otherwise a reload will fail with 'address already in use'
            time.sleep(.2)