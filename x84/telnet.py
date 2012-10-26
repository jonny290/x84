# -*- coding: utf-8 -*-
"""
Handle Asynchronous Telnet Connections.
Single-process, no threads, select-based.

Limitations:
 - No linemode support, character-at-a-time only.
 - No out-of-band / data mark (DM) / sync supported
   (no ^C, ^S, ^Q helpers)

This is a modified version of miniboa retrieved from
svn address http://miniboa.googlecode.com/svn/trunk/miniboa
which is meant for MUD's. This server would not be safe for MUD clients.
"""
#  Copyright 2012 Jeff Quast, whatever Jim's license is; changes from miniboa:
#    character-at-a-time input instead of linemode, encoding option on send,
#    strict rejection of linemode, terminal type detection, environment
#    variable support, GA and SGA, utf-8 safe

#------------------------------------------------------------------------------
#   miniboa/async.py
#   miniboa/telnet.py
#   Copyright 2009 Jim Storch
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain a
#   copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#------------------------------------------------------------------------------

import warnings
import inspect
import socket
import select
import array
import time
import sys
import os
import logging

import bbs.exception

#pylint: disable=C0103
#        Invalid name "logger" for type constant
logger = logging.getLogger()

#--[ Telnet Options ]----------------------------------------------------------
from telnetlib import LINEMODE, NAWS, NEW_ENVIRON, ENCRYPT
from telnetlib import BINARY, SGA, ECHO, STATUS, TTYPE
from telnetlib import IAC, DONT, DO, WONT, WILL
from telnetlib import SE, NOP, DM, BRK, IP, AO, AYT, EC, EL, GA, SB
IS      = chr(0)        # Sub-process negotiation IS command
SEND    = chr(1)        # Sub-process negotiation SEND command
NEGOTIATE_STATUS = (ECHO, SGA, LINEMODE, TTYPE, NAWS, NEW_ENVIRON,)

class TelnetServer(object):
    """
    Poll sockets for new connections and sending/receiving data from clients.
    """
    MAX_CONNECTIONS = 1000
    TIME_POLL = 0.01
    LISTEN_BACKLOG = 5
    ## Dictionary of active clients, (file descriptor, TelnetClient,)
    clients = {}
    ## Dictionary of environment variables received by negotiation
    env = {}
    def __init__(self, address_pair, on_connect, on_disconnect, on_naws):
        """
        Create a new Telnet Server.

        Arguments:
           address_pair: tuple of (ip, port) to bind to.
           on_connect: this callback receives TelnetClient after a
                       connection is initiated.
           on_disconnect: this callback receives TelnetClient after
                          connect is lost.
           on_naws: this callable receives a TelnetClient when a client
                    negotiates about window size (resize event).
        """
        (self.address, self.port) = address_pair
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_naws = on_naws

        # bind
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(address_pair)
            self.server_socket.listen(self.LISTEN_BACKLOG)
        except socket.error, err:
            logger.error ('Unable to bind: %s', err)
            sys.exit (1)

    def client_count(self):
        """
        Returns the number of active connections.
        """
        return len(self.clients)

    def client_list(self):
        """
        Returns a list of connected clients.
        """
        return self.clients.values()

    def poll(self):
        """
        Perform a non-blocking scan of recv and send states on the server
        and client connection sockets.  Process new connection requests,
        read incomming data, and send outgoing data.  Sends and receives may
        be partial.
        """

        ## Delete inactive connections
        for client in (c for c in self.clients.values() if c.active is False):
            fileno = client.sock.fileno()
            client.sock.close ()
            logger.debug ('%s: deleted', client.addrport())
            del self.clients[fileno]
            if self.on_disconnect is not None:
                self.on_disconnect (client)

        ## Build a list of connections to test for receive data
        recv_list = [self.server_socket.fileno()] + [c.sock.fileno()
            for c in self.clients.values() if c.active]

        ## Build a list of connections that have data to receieve
        #pylint: disable=W0612
        #        Unused variable 'elist'
        rlist, slist, elist = select.select(recv_list, [], [], self.TIME_POLL)

        if self.server_socket.fileno() in rlist:
            try:
                sock, address_pair = self.server_socket.accept()
            except socket.error, err:
                logger.error ('accept error %d:%s', err[0], err[1],)
                return

            ## Check for maximum connections
            if self.client_count() < self.MAX_CONNECTIONS:
                client = TelnetClient(sock, address_pair, self.on_naws)
                ## Add the connection to our dictionary and call handler
                self.clients[client.sock.fileno()] = client
                self.on_connect (client)
            else:
                logger.error ('refused new connect; maximum reached.')
                sock.close()

        ## Process sockets with data to receive
        recv_ready = (self.clients[f] for f in rlist
            if f != self.server_socket.fileno())
        for client in recv_ready:
            try:
                client.socket_recv ()
            except bbs.exception.ConnectionClosed, err:
                logger.debug ('%s connection closed: %s.',
                        client.addrport(), err)
                client.deactivate()

        ## Process sockets with data to send
        slist = (c for c in self.clients.values()
            if c.active and c.send_ready())
        for client in slist:
            try:
                client.socket_send ()
            except bbs.exception.ConnectionClosed, err:
                logger.debug ('%s connection closed: %s.',
                        client.addrport(), err)
                client.deactivate()

#---[ Telnet Notes ]-----------------------------------------------------------
# (See RFC 854 for more information)
#
# Negotiating a Local Option
# --------------------------
#
# Side A begins with:
#
#    "IAC WILL/WONT XX"   Meaning "I would like to [use|not use] option XX."
#
# Side B replies with either:
#
#    "IAC DO XX"     Meaning "OK, you may use option XX."
#    "IAC DONT XX"   Meaning "No, you cannot use option XX."
#
#
# Negotiating a Remote Option
# ----------------------------
#
# Side A begins with:
#
#    "IAC DO/DONT XX"  Meaning "I would like YOU to [use|not use] option XX."
#
# Side B replies with either:
#
#    "IAC WILL XX"   Meaning "I will begin using option XX"
#    "IAC WONT XX"   Meaning "I will not begin using option XX"
#
#
# The syntax is designed so that if both parties receive simultaneous requests
# for the same option, each will see the other's request as a positive
# acknowledgement of it's own.
#
# If a party receives a request to enter a mode that it is already in, the
# request should not be acknowledged.

## Where you see DE in my comments I mean 'Distant End', e.g. the client.

UNKNOWN = -1

#-----------------------------------------------------------------Telnet Option

class TelnetOption(object):
    """
    Simple class used to track the status of an extended Telnet option.
    Attributes and values:
        local_option: UNKNOWN (default), True, or False.
        remote_option: UNKNOWN (default), True, or False.
        reply_pending: True or Fale.
    """
    # pylint: disable=R0903
    #         Too few public methods (0/2)
    def __init__(self):
        """
        Set attribute defaults on init.
        """
        self.local_option = UNKNOWN     # Local state of an option
        self.remote_option = UNKNOWN    # Remote state of an option
        self.reply_pending = False      # Are we expecting a reply?

def name_option(option):
    """
    Perform introspection of global CONSTANTS for equivalent values,
    and return a string that displays its possible meanings
    """
    values = ';?'.join([k for k, v in globals().iteritems()
        if option == v and k not in ('SEND', 'IS',)])
    return values if values != '' else str(ord(option))

def debug_option(func):
    """
    This function is a decorator that debug prints the 'from' address for
    callables decorated with this. This helps during telnet negotiation, to
    understand which function sets or checks local or remote option states.
    """
    def wrapper(self, *args):
        """
        inner wrapper for debug_option
        """
        stack = inspect.stack()
        logger.debug ('%s:%s %s(%s%s)',
            os.path.basename(stack[1][1]), stack[1][2],
            func.__name__, name_option(args[0]),
            ', %s' % (args[1],) if len(args) == 2 else '')
        return func(self, *args)
    return wrapper


#------------------------------------------------------------------------Telnet

class TelnetClient(object):
    """
    Represents a remote Telnet Client, instantiated from TelnetServer.
    """
    # pylint: disable=R0902
    #         Too many instance attributes (15/7)
    BLOCKSIZE_RECV = 64
    SB_MAXLEN = 65534 # maximum length of subnegotiation string, allow
                      # a fairly large one for NEW_ENVIRON negotiation

    def __init__(self, sock, address_pair, on_naws=None):
        """
        Arguments:
            sock: socket
            address_pair: tuple (ip address, port number)
            on_naws: callback for window resizing by client
        """
        self.sock = sock
        self.address_pair = address_pair
        self.on_naws = on_naws
        self.active = True
        self.env = dict([('TERM', 'unknown'),])
        self.send_buffer = array.array('c')
        self.recv_buffer = array.array('c')
        self.telnet_sb_buffer = array.array('c')
        self.bytes_received = 0
        self.connect_time = time.time()
        self.last_input_time = time.time()

        ## State variables for interpreting incoming telnet commands
        self.telnet_got_iac = False
        self.telnet_got_cmd = None
        self.telnet_got_sb = False
        self.telnet_opt_dict = {}

    def get_input(self):
        """
        Get any input bytes received from the DE. The input_ready method
        returns True when bytes are available.
        """
        data = self.recv_buffer.tostring ()
        self.recv_buffer = array.array('c')
        return data

    def send_str(self, bytestring):
        """
        buffer bytestrings for sending to the distant end.
        """
        self.send_buffer.fromstring (bytestring)

    def send_unicode(self, unibytes, encoding='utf8'):
        """
        buffer unicode data, encoded to bytestrings as 'encoding'
        """
        bytestring = unibytes.encode(encoding, 'replace')
        ## Must be escaped 255 (IAC + IAC) to avoid IAC intepretation
        bytestring = bytestring.replace(chr(255), 2*chr(255))
        self.send_str (bytestring)

    def deactivate(self):
        """
        Set the client to disconnect on the next server poll.
        """
        logger.debug ('%s: marked for deactivation', self.addrport())
        self.active = False

    def addrport(self):
        """
        Return the DE's IP address and port number as a string.
        """
        return '%s:%d' % (self.address_pair[0], self.address_pair[1])

    def idle(self):
        """
        Returns the number of seconds that have elasped since the DE
        last sent us some input.
        """
        return time.time() - self.last_input_time


    def duration(self):
        """
        Returns the number of seconds the DE has been connected.
        """
        return time.time() - self.connect_time


    def request_will_sga(self):
        """
        Request DE to Suppress Go-Ahead.  See RFC 858.
        """
        self._iac_will(SGA)
        self._note_reply_pending(SGA, True)


    def request_will_echo(self):
        """
        Tell the DE that we would like to echo their text.  See RFC 857.
        """
        self._iac_will(ECHO)
        self._note_reply_pending(ECHO, True)


    def request_wont_echo(self):
        """
        Tell the DE that we would like to stop echoing their text.
        See RFC 857.
        """
        self._iac_wont(ECHO)
        self._note_reply_pending(ECHO, True)


    def request_do_sga(self):
        """
        Request to Negotiate SGA.  See ...
        """
        self._iac_do(SGA)
        self._note_reply_pending(SGA, True)


    def request_do_naws(self):
        """
        Request to Negotiate About Window Size.  See RFC 1073.
        """
        self._iac_do(NAWS)
        self._note_reply_pending(NAWS, True)

    def request_do_env(self):
        """
        Request to Negotiate About Window Size.  See RFC 1073.
        """
        self._iac_do(NEW_ENVIRON)
        self._note_reply_pending(NEW_ENVIRON, True)
        self.request_env ()

    def request_env(self):
        """
        Request sub-negotiation NEW_ENVIRON. See RFC 1572.
        """
        # chr(0) indicates VAR request,
        #  followed by variable name,
        # chr(3) indicates USERVAR request,
        # chr(0)
        self.send_str (bytes(''.join((IAC, SB, NEW_ENVIRON, SEND, chr(0)))))
        self.send_str (bytes(chr(0).join( \
            ("USER", "TERM", "SHELL", "COLUMNS", "LINES", "LC_CTYPE",
            "XTERM_LOCALE", "DISPLAY", "SSH_CLIENT", "SSH_CONNECTION",
            "SSH_TTY", "HOME", "HOSTNAME", "PWD", "MAIL", "LANG", "PWD",
            "UID", "USER_ID", "EDITOR", "LOGNAME"))))
        self.send_str (bytes(''.join((chr(3), IAC, SE))))

    def request_ttype(self):
        """
        Request sub-negotiation ttype.  See RFC 779.
        A successful response will set self.env['TERM']
        """
        self.send_str (bytes(''.join((IAC, SB, TTYPE, SEND, IAC, SE))))

    def send_ready(self):
        """
        Return True if any data is buffered for sending (screen output).
        """
        return bool(0 != self.send_buffer.__len__())

    def input_ready(self):
        """
        Return True if any data is buffered for reading (keyboard input).
        """
        return bool(0 != self.recv_buffer.__len__())

    def socket_send(self):
        """
        Called by TelnetServer.poll() when send data is ready.  Send any
        data buffered, trim self.send_buffer to bytes sent, and return number of bytes sent. bbs.exception.ConnectionClosed may be raised.
        """
        if not self.send_ready():
            warnings.warn ('socket_send() called on empty buffer',
                    RuntimeWarning, 2)
            return 0
        def send(send_bytes):
            """
            raises bbs.exception.ConnectionClosed on sock.send err
            """
            try:
                return self.sock.send(send_bytes)
            except socket.error, err:
                raise bbs.exception.ConnectionClosed (
                        'socket send %d:%s' % (err[0], err[1],))
        ready_bytes = bytes(''.join(self.send_buffer))
        sent = send(ready_bytes)
        self.send_buffer = array.array('c')
        if sent < len(ready_bytes):
            # re-buffer data that could not be pushed to socket;
            self.send_buffer.fromstring (ready_bytes[sent:])
        else:
            # When a process has completed sending data to an NVT printer
            # and has no queued input from the NVT keyboard for further
            # processing (i.e., when a process at one end of a TELNET
            # connection cannot proceed without input from the other end),
            # the process must transmit the TELNET Go Ahead (GA) command.
            if (not self.input_ready()
                    and self._check_local_option(SGA) in (False, UNKNOWN)):
                sent += send(bytes(''.join((IAC, GA))))
        return sent


    def socket_recv(self):
        """
        Called by TelnetServer.poll() when recv data is ready.  Read any
        data on socket, processing telnet commands, and buffering all
        other bytestrings to self.recv_buffer.  If data is not received,
        or the connection is closed, bbs.exception.ConnectionClosed is raised.
        """
        recv = 0
        try:
            data = self.sock.recv (self.BLOCKSIZE_RECV)
            recv = len(data)
            if 0 == recv:
                raise bbs.exception.ConnectionClosed ('Requested by client')
        except socket.error, err:
            raise bbs.exception.ConnectionClosed (
                    'socket errorno %d: %s' % (err[0], err[1],))
        self.bytes_received += recv
        self.last_input_time = time.time()

        ## Test for telnet commands, non-telnet bytes
        ## are pushed to self.recv_buffer (side-effect),
        for byte in data:
            self._iac_sniffer(byte)
        return recv

    def _recv_byte(self, byte):
        """
        Buffer non-telnet commands bytestrings into recv_buffer.
        """
        self.recv_buffer.fromstring(byte)

    def _iac_sniffer(self, byte):
        """
        Watches incomming data for Telnet IAC sequences.
        Passes the data, if any, with the IAC commands stripped to
        _recv_byte().
        """
        ## Are we not currently in an IAC sequence coming from the DE?
        if self.telnet_got_iac is False:
            if byte == IAC:
                self.telnet_got_iac = True
            ## Are we currenty in a sub-negotion?
            elif self.telnet_got_sb is True:
                self.telnet_sb_buffer.fromstring (byte)
                ## Sanity check on length
                if len(self.telnet_sb_buffer) >= self.SB_MAXLEN:
                    raise bbs.exception.ConnectionClosed (
                            'sub-negotiation buffer filled')
            else:
                ## Just a normal NVT character
                self._recv_byte (byte)
            return

        ## Did we get sent a second IAC?
        if byte == IAC and self.telnet_got_sb is True:
            ## Must be an escaped 255 (IAC + IAC)
            self.telnet_sb_buffer.fromstring (byte)
            self.telnet_got_iac = False
        ## Do we already have an IAC + CMD?
        elif self.telnet_got_cmd is not None:
            ## Yes, so handle the option
            self._three_byte_cmd(byte)
        ## We have IAC but no CMD
        else:
            ## Is this the middle byte of a three-byte command?
            if byte in (DO, DONT, WILL, WONT):
                self.telnet_got_cmd = byte
            else:
                ## Nope, must be a two-byte command
                self._two_byte_cmd(byte)

    def _two_byte_cmd(self, cmd):
        """
        Handle incoming Telnet commands that are two bytes long.
        """
        #logger.debug ('recv _two_byte_cmd %s', name_option(cmd),)
        if cmd == SB:
            ## Begin capturing a sub-negotiation string
            self.telnet_got_sb = True
            self.telnet_sb_buffer = array.array('c')
        elif cmd == SE:
            ## Stop capturing a sub-negotiation string
            self.telnet_got_sb = False
            self._sb_decoder()
            logger.debug ('decoded (SE)')
        elif cmd == IP:
            self.deactivate ()
            logger.warn ('Interrupt Process (IP); closing.')
        elif cmd == AO:
            flushed = len(self.recv_buffer)
            self.recv_buffer = array.array('c')
            logger.debug ('Abort Output (AO); %s bytes discarded.', flushed)
        elif cmd == AYT:
            self.send_str (bytes('\b'))
            logger.debug ('Are You There (AYT); "\\b" sent.')
        elif cmd == EC:
            self.recv_buffer.fromstring ('\b')
            logger.debug ('Erase Character (EC); "\\b" queued.')
        elif cmd == EL:
            logger.warn ('Erase Line (EC) received; ignored.')
        elif cmd == GA:
            logger.warn ('Go Ahead (GA) received; ignored.')
        elif cmd == NOP:
            logger.debug ('NUL ignored.')
        elif cmd == DM:
            logger.warn ('Data Mark (DM) received; ignored.')
        elif cmd == BRK:
            logger.warn ('Break (BRK) received; ignored.')
        else:
            logger.error ('_two_byte_cmd invalid: %r', cmd)
        self.telnet_got_iac = False
        self.telnet_got_cmd = None

    def _three_byte_cmd(self, option):
        """
        Handle incoming Telnet commmands that are three bytes long.
        """
        cmd = self.telnet_got_cmd
        logger.debug ('recv IAC %s %s', name_option(cmd), name_option(option))
        # Incoming DO's and DONT's refer to the status of this end

        if cmd == DO:
            self._handle_do (option)
        elif cmd == DONT:
            self._handle_dont (option)
        elif cmd == WILL:
            self._handle_will (option)
        elif cmd == WONT:
            self._handle_wont (option)
        else:
            logger.warn ('%s: unhandled _three_byte_cmd: %s.',
                    self.addrport(), name_option(option))
        self.telnet_got_iac = False
        self.telnet_got_cmd = None

    def _handle_do(self, option):
        """
        Process a DO command option received by DE.
        """
        self._note_reply_pending(option, False)
        if option == ECHO:
            # DE requests us to echo their input
            if self._check_local_option(ECHO) is not True:
                self._note_local_option(ECHO, True)
                self._iac_will(ECHO)
        elif option == SGA:
            # DE wants us to supress go-ahead
            if self._check_local_option(SGA) is not True:
                self._note_local_option(SGA, True)
                self._iac_will(SGA)
                self._iac_do(SGA)
                # always send DO SGA after WILL SGA, requesting the DE
                # also supress their go-ahead. this order seems to be the
                # 'magic sequence' to disable linemode on certain clients
        elif option == LINEMODE:
            # DE wants to do linemode editing
            # denied
            if self._check_local_option(option) is not False:
                self._note_local_option(option, False)
                self._iac_wont(LINEMODE)
        elif option == ENCRYPT:
            # DE is willing to receive encrypted data
            # denied
            if self._check_local_option(option) is not False:
                self._note_local_option(option, False)
                # let DE know we refuse to send encrypted data.
                self._iac_wont(ENCRYPT)
        elif option == STATUS:
            # DE wants us to report our status
            if self._check_local_option(option) is not True:
                self._note_local_option(option, True)
                self._iac_will(STATUS)
                self._send_status ()
        else:
            if self._check_local_option(option) is UNKNOWN:
                self._note_local_option(option, False)
                logger.warn ('%s: unhandled do: %s.',
                    self.addrport(), name_option(option))
                self._iac_wont(option)

    def _send_status(self):
        """
        Process a DO STATUS command option received by DE.
        The sender of the WILL STATUS is free to transmit status
        information, spontaneously or in response to a request
        from the sender of the DO.
        """
        self.send_str (bytes(''.join((IAC, SB, STATUS, IS))))
        for opt in NEGOTIATE_STATUS:
            local_status = self._check_local_option(opt)
            if local_status:
                logger.debug ('local status, DO %s',
                        name_option(opt))
                self.send_str(bytes(''.join((DO, opt))))
            elif local_status:
                logger.debug ('local status, DONT %s',
                        name_option(opt))
                self.send_str(bytes(''.join((DONT, opt))))
            else:
                assert local_status is UNKNOWN
                logger.debug ('local status, UNKNOWN %s (not sent)',
                        name_option(opt))
            remote_status = self._check_remote_option(opt)
            if remote_status:
                logger.debug ('remote status, DO %s',
                        name_option(opt))
                self.send_str(bytes(''.join((DO, opt))))
            elif remote_status:
                logger.debug ('remote status, DONT %s',
                        name_option(opt))
                self.send_str(bytes(''.join((DONT, opt))))
            else:
                assert remote_status is UNKNOWN
                logger.debug ('remote status, UNKNOWN %s (not sent)',
                        name_option(opt))
        self.send_str (bytes(''.join((IAC, SE))))

    def _handle_dont(self, option):
        """
        Process a DONT command option received by DE.
        """
        self._note_reply_pending(option, False)
        if option == BINARY:
            # client demands no binary mode
            if self._check_local_option(BINARY) is not False:
                self._note_local_option (BINARY, False)
                self._iac_wont(BINARY) # agree
        elif option == ECHO:
            # client demands we do not echo
            if self._check_local_option(ECHO) is not False:
                self._note_local_option(ECHO, False)
                self._iac_wont(ECHO) # agree
        elif option == SGA:
            # DE demands that we start or continue transmitting
            # GAs (go-aheads) when transmitting data.
            if self._check_local_option(SGA) is not False:
                self._note_local_option(SGA, False)
                self._iac_wont(SGA)
        elif option == LINEMODE:
            # client demands no linemode.
            if self._check_remote_option(LINEMODE) is not False:
                self._note_remote_option(LINEMODE, False)
                self._iac_wont(LINEMODE)
        else:
            logger.warn ('%s: unhandled dont: %s.',
                self.addrport(), name_option(option))

    def _handle_will(self, option):
        """
        Process a WILL command option received by DE.
        """
        #pylint: disable=R0912
        #        Too many branches (19/12)
        if self._check_reply_pending(option):
            self._note_reply_pending(option, False)
        if option == ECHO:
            raise bbs.exception.ConnectionClosed \
                ('Refuse WILL ECHO by client, closing connection.')
        elif option == NAWS:
            if self._check_remote_option(NAWS) is not True:
                self._note_remote_option(NAWS, True)
                self._note_local_option(NAWS, True)
                self._iac_do(NAWS)
        elif option == STATUS:
            if self._check_remote_option(STATUS) is not True:
                self._note_remote_option(STATUS, True)
                self.send_str (bytes(''.join((
                    IAC, SB, STATUS, SEND, IAC, SE)))) # go ahead
        elif option == ENCRYPT:
            # DE is willing to send encrypted data
            # denied
            if self._check_local_option(ENCRYPT) is not False:
                self._note_local_option(ENCRYPT, False)
                # let DE know we refuse to receive encrypted data.
                self._iac_dont(ENCRYPT)
        elif option == LINEMODE:
            if self._check_local_option(LINEMODE) is not False:
                self._note_local_option(LINEMODE, False)
                # let DE know we refuse to do linemode
                self._iac_dont(LINEMODE)
        elif option == SGA:
            #  IAC WILL SUPPRESS-GO-AHEAD
            #
            # The sender of this command requests permission to begin
            # suppressing transmission of the TELNET GO AHEAD (GA)
            # character when transmitting data characters, or the
            # sender of this command confirms it will now begin suppressing
            # transmission of GAs with transmitted data characters.
            if self._check_remote_option(SGA) is not True:
                self._note_remote_option(SGA, True)
                self._note_local_option(SGA, True)
                self._iac_will(SGA)
        elif option == NEW_ENVIRON:
            if self._check_reply_pending(NEW_ENVIRON):
                self._note_reply_pending(NEW_ENVIRON, False)
            if self._check_remote_option(NEW_ENVIRON) in (False, UNKNOWN):
                self._note_remote_option(NEW_ENVIRON, True)
                self._note_local_option(NEW_ENVIRON, True)
                self._iac_do(NEW_ENVIRON)
                self.request_env ()
        elif option == TTYPE:
            if self._check_reply_pending(TTYPE):
                self._note_reply_pending(TTYPE, False)
            if self._check_remote_option(TTYPE) in (False, UNKNOWN):
                self._note_remote_option(TTYPE, True)
                self._iac_do(TTYPE)
                # trigger SB response
                self.send_str (bytes(''.join( \
                    (IAC, SB, TTYPE, SEND, IAC, SE))))
        else:
            logger.warn ('%s: unhandled will: %r (ignored).',
                self.addrport(), name_option(option))

    def _handle_wont (self, option):
        """
        Process a WONT command option received by DE.
        """
        if option == ECHO:
            if self._check_remote_option(ECHO) in (True, UNKNOWN):
                self._note_remote_option(ECHO, False)
                self._iac_dont(ECHO)
        elif option == SGA:
            if self._check_reply_pending(SGA):
                self._note_reply_pending(SGA, False)
                self._note_remote_option(SGA, False)
            elif self._check_remote_option(SGA) in (True, UNKNOWN):
                self._note_remote_option(SGA, False)
                self._iac_dont(SGA)
        elif option == TTYPE:
            if self._check_reply_pending(TTYPE):
                self._note_reply_pending(TTYPE, False)
                self._note_remote_option(TTYPE, False)
            elif self._check_remote_option(TTYPE) in (True, UNKNOWN):
                self._note_remote_option(TTYPE, False)
                self._iac_dont(TTYPE)
        else:
            logger.debug ('%s: unhandled wont: %s.',
                self.addrport(), name_option(option))


    def _sb_decoder(self):
        """
        Figures out what to do with a received sub-negotiation block.
        """
        buf = self.telnet_sb_buffer
        if 0 == len(buf):
            logger.error ('nil SB')
            return
        if 1 == len(buf) and buf[0] == chr(0):
            logger.error ('0nil SB')
            return
        elif (TTYPE, IS) == (buf[0], buf[1]):
            self._sb_ttype (buf[2:].tostring())
        elif (NEW_ENVIRON, IS) == (buf[0], buf[1],):
            self._sb_env (buf[2:].tostring())
        elif (NAWS,) == (buf[0],):
            self._sb_naws (buf)
        elif (STATUS, SEND) == buf([0], buf[1]):
            self._send_status ()
            # Sender requests receiver to transmit his (the receiver's)
            # perception of the current status of Telnet
            # options. The code for SEND is 1. (See below.)
        else:
            logger.error ('unsupported subnegotiation, %s: %r',
                    name_option(buf[0]), buf,)
        self.telnet_sb_buffer = ''

    def _sb_ttype(self, bytestring):
        """
        Processes incoming subnegotiation TTYPE
        """
        term_str = bytestring.lower()
        prev_term = self.env.get('TERM', None)
        if prev_term is None:
            logger.info ("env['TERM'] = %r.", term_str,)
        elif prev_term != term_str:
            logger.info ("env['TERM'] = %r by TTYPE%s.", term_str,
                    'was: %s' %(prev_term,) if prev_term != 'unknown' else '')
        else:
            logger.debug ('TTYPE ignored (TERM already set).')
        self.env['TERM'] = term_str

    def _sb_env (self, bytestring):
        """
        Processes incoming subnegotiation NEW_ENVIRON
        """
        breaks = list([idx for (idx, byte) in enumerate(bytestring)
            if byte in (chr(0), chr(3))])
        for start, end in zip(breaks, breaks[1:]):
            #logger.debug ('%r', bytestring[start+1:end])
            pair = bytestring[start+1:end].split(chr(1))
            if len(pair) == 1:
                if (pair[0] in self.env
                        and pair[0] not in ('LINES', 'COLUMNS', 'TERM')):
                    logger.warn ("del env[%r]", pair[0])
                    del self.env[pair[0]]
            elif len(pair) == 2:
                if pair[0] == 'TERM':
                    pair[1] = pair[1].lower()
                if (not pair[0] in self.env or (pair[0] == 'TERM' and
                    self.env['TERM'] == 'unknown')):
                    logger.info ('env[%r] = %r', pair[0], pair[1])
                    self.env[pair[0]] = pair[1]
                elif pair[1] == self.env[pair[0]]:
                    logger.debug ('env[%r] = %r (repeated)',
                        pair[0], pair[1])
                else:
                    logger.warn ('%s conflict: %s (ignored)', pair[0], pair[1])
            else:
                logger.error ('client NEW_ENVIRON; invalid %r', pair)

    def _sb_naws(self, charbuf):
        """
        Processes incoming subnegotiation NAWS
        """
        if 5 != len(charbuf):
            logger.error('%s: bad length in NAWS buf (%d)',
                self.addrport(), len(charbuf),)
            return
        columns = str((256 * ord(charbuf[1])) + ord(charbuf[2]))
        rows = str((256 * ord(charbuf[3])) + ord(charbuf[4]))
        if (self.env.get('LINES', None) == rows
                and self.env.get('COLUMNS', None) == columns):
            logger.debug ('.. naws repeated and ignored')
        else:
            self.env['LINES'] = str(rows)
            self.env['COLUMNS'] = str(columns)
            logger.debug ('%s: window size is %sx%s',
                    self.addrport(), columns, rows)
            if self.on_naws is not None:
                self.on_naws (self)


    #---[ State Juggling for Telnet Options ]----------------------------------

    ## Sometimes verbiage is tricky.  I use 'note' rather than 'set' here
    ## because (to me) set infers something happened.

    #@debug_option
    def _check_local_option(self, option):
        """
        Test the status of local negotiated Telnet options.
        """
        if not self.telnet_opt_dict.has_key(option):
            self.telnet_opt_dict[option] = TelnetOption()
        return self.telnet_opt_dict[option].local_option

    #@debug_option
    def _note_local_option(self, option, state):
        """
        Record the status of local negotiated Telnet options.
        """
        if not self.telnet_opt_dict.has_key(option):
            self.telnet_opt_dict[option] = TelnetOption()
        self.telnet_opt_dict[option].local_option = state

    #@debug_option
    def _check_remote_option(self, option):
        """
        Test the status of remote negotiated Telnet options.
        """
        if not self.telnet_opt_dict.has_key(option):
            self.telnet_opt_dict[option] = TelnetOption()
        return self.telnet_opt_dict[option].remote_option

    #@debug_option
    def _note_remote_option(self, option, state):
        """
        Record the status of local negotiated Telnet options.
        """
        if not option in self.telnet_opt_dict:
            self.telnet_opt_dict[option] = TelnetOption()
        self.telnet_opt_dict[option].remote_option = state

    #@debug_option
    def _check_reply_pending(self, option):
        """
        Test the status of requested Telnet options.
        """
        if not option in self.telnet_opt_dict:
            self.telnet_opt_dict[option] = TelnetOption()
        return self.telnet_opt_dict[option].reply_pending

    #@debug_option
    def _note_reply_pending(self, option, state):
        """
        Record the status of requested Telnet options.
        """
        if not option in self.telnet_opt_dict:
            self.telnet_opt_dict[option] = TelnetOption()
        self.telnet_opt_dict[option].reply_pending = state


    #---[ Telnet Command Shortcuts ]-------------------------------------------

    def _iac_do(self, option):
        """
        Send a Telnet IAC "DO" sequence.
        """
        logger.debug ('send IAC DO %s', name_option(option))
        self.send_str (bytes(''.join((IAC, DO, option))))

    def _iac_dont(self, option):
        """
        Send a Telnet IAC "DONT" sequence.
        """
        logger.debug ('send IAC DONT %s', name_option(option))
        self.send_str (bytes(''.join((IAC, DONT, option))))

    def _iac_will(self, option):
        """
        Send a Telnet IAC "WILL" sequence.
        """
        logger.debug ('send IAC WILL %s', name_option(option))
        self.send_str (bytes(''.join((IAC, WILL, option))))

    def _iac_wont(self, option):
        """
        Send a Telnet IAC "WONT" sequence.
        """
        logger.debug ('send IAC WONT %s', name_option(option))
        self.send_str (bytes(''.join((IAC, WONT, option))))