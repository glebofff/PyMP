# coding=utf-8

from plugin import Plugin
import socket
from ..packet import Packet
from ..auth.challenge import Challenge
from ..auth.response import Response
from ..flags import Flags
from ..resultset import ResultSet
from ..com.initdb import Initdb
from ..com.query import Query
from ..com.quit import Quit


class Proxy(Plugin):
    serverSocket = None

    def init(self, context):
        context.logger.info('Proxy.init')
        self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serverSocket.setsockopt(socket.IPPROTO_TCP,
                                     socket.TCP_NODELAY,
                                     1)
        self.serverSocket.setsockopt(socket.SOL_SOCKET,
                                     socket.SO_KEEPALIVE,
                                     1)
        self.serverSocket.settimeout(None)
        self.serverSocket.connect((context.config[
            'plugins']['Proxy']['remoteHost'],
                                   int(
                                    context.config[
                                        'plugins']['Proxy']['remotePort']
                                    )))

    def read_handshake(self, context):
        packet = Packet.read_packet(self.serverSocket)
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
        packet = Packet.read_packet(context.clientSocket)
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
        packet = Packet.read_packet(self.serverSocket)
        if Packet.getType(packet) != Flags.OK:
            context.logger.fatal('Auth is not okay!')
        context.buff.extend(packet)

    def send_auth_result(self, context):
        context.clientSocket.sendall(context.buff)
        context.buff = bytearray()

    def read_query(self, context):
        context.bufferResultSet = False
        context.expectedResultSet = Flags.RS_FULL

        packet = Packet.read_packet(context.clientSocket)
        context.sequenceId = Packet.getSequenceId(packet)
        context.logger.info('Client sequenceId: %s' % context.sequenceId)

        packet_type = Packet.getType(packet)

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
        packet = Packet.read_packet(self.serverSocket)
        context.sequenceId = Packet.getSequenceId(packet)

        packetType = Packet.getType(packet)
        context.buff.extend(packet)

        if packetType != Flags.OK and packetType != Flags.ERR:
            Packet.read_full_result_set(
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
