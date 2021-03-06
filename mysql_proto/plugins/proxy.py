# coding=utf-8

from ..auth.challenge import Challenge
from ..auth.response import Response
from ..com.initdb import Initdb
from ..com.query import Query
from ..com.quit import Quit
from ..flags import Flags
from ..packet import read_packet
from ..packet import getType
from ..packet import getSequenceId
from ..packet import read_full_result_set
from plugin import Plugin
from ..resultset import ResultSet
import socket


class Proxy(Plugin):
    __slots__ = ('serverSocket')

    def init(self, context):
        super(Proxy, self).__init__()

        context.logger.info('Proxy.init')
        self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serverSocket.setsockopt(socket.IPPROTO_TCP,
                                     socket.TCP_NODELAY,
                                     1)
        self.serverSocket.setsockopt(socket.SOL_SOCKET,
                                     socket.SO_KEEPALIVE,
                                     1)
        self.serverSocket.settimeout(None)
        self.serverSocket.connect(
            (context.config['plugins']['Proxy']['remoteHost'],
             int(context.config['plugins']['Proxy']['remotePort'])))

    def read_handshake(self, context):
        packet = read_packet(self.serverSocket)
        context.authChallenge = Challenge.loadFromPacket(packet)
        context.authChallenge.removeCapabilityFlag(Flags.CLIENT_COMPRESS)
        context.authChallenge.removeCapabilityFlag(Flags.CLIENT_SSL)
        context.authChallenge.removeCapabilityFlag(Flags.CLIENT_LOCAL_FILES)

        ResultSet.characterSet = context.authChallenge.characterSet

        context.buff.extend(context.authChallenge.toPacket())

    def send_handshake(self, context):
        context.clientSocket.sendall(context.buff)
        context.buff = bytearray()

    def read_auth(self, context):
        packet = read_packet(context.clientSocket)
        context.authReply = Response.loadFromPacket(packet)

        if not context.authReply.hasCapabilityFlag(Flags.CLIENT_PROTOCOL_41):
            context.logger.fatal('We do not support Protocols under 4.1')
            context.halt()
            return

        context.authReply.removeCapabilityFlag(Flags.CLIENT_COMPRESS)
        context.authReply.removeCapabilityFlag(Flags.CLIENT_SSL)
        context.authReply.removeCapabilityFlag(Flags.CLIENT_LOCAL_FILES)

        context.schema = context.authReply.schema

        context.buff.extend(context.authReply.toPacket())

    def send_auth(self, context):
        self.serverSocket.sendall(context.buff)
        context.buff = bytearray()

    def read_auth_result(self, context):
        packet = read_packet(self.serverSocket)
        if getType(packet) != Flags.OK:
            context.logger.fatal('Auth is not okay!')
        context.buff.extend(packet)

    def send_auth_result(self, context):
        context.clientSocket.sendall(context.buff)
        context.buff = bytearray()

    def read_query(self, context):
        context.bufferResultSet = False
        context.expectedResultSet = Flags.RS_FULL

        packet = read_packet(context.clientSocket)
        context.sequenceId = getSequenceId(packet)
        context.logger.info('Client sequenceId: %s' % context.sequenceId)

        packet_type = getType(packet)

        if packet_type == Flags.COM_QUIT:
            context.halt()
        elif packet_type == Flags.COM_INIT_DB:
            context.schema = Initdb.loadFromPacket(packet).schema
        elif packet_type == Flags.COM_QUERY:
            context.query = Query.loadFromPacket(packet).query
        elif packet_type == Flags.COM_FIELD_LIST:
            context.expectedResultSet = Flags.RS_HALF

        context.buff.extend(packet)

    def send_query(self, context):
        self.serverSocket.sendall(context.buff)
        context.buff = bytearray()

    def read_query_result(self, context):
        packet = read_packet(self.serverSocket)
        context.sequenceId = getSequenceId(packet)

        packetType = getType(packet)
        context.buff.extend(packet)

        if packetType != Flags.OK and packetType != Flags.ERR:
            read_full_result_set(
                self.serverSocket,
                context.clientSocket,
                context.buff,
                context.bufferResultSet,
                resultsetType=context.expectedResultSet
            )

    def send_query_result(self, context):
        context.clientSocket.sendall(context.buff)
        context.buff = bytearray()

    def cleanup(self, context):
        pass

    def shutdown(self, context):
        obj = Quit()
        obj.sequenceId = 0
        self.serverSocket.sendall(obj.toPacket())
        self.serverSocket.close()
