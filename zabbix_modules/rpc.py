from __future__ import absolute_import

import functools
import json
import logging
import struct
import weakref

import six


_LENGTH = '!I'
_RPC_PREFIX = 'remote_'


_log = logging.getLogger(__name__)


def _length_to_bytes(length):
    return struct.pack(_LENGTH, length)


_LENGTH_LENGTH = len(_length_to_bytes(0))


def _bytes_to_length(data):
    return struct.unpack(_LENGTH, data)[0]


class Server(object):
    def __init__(self, stream, target):
        self._stream = weakref.ref(stream)
        self._target = target

        self._buffer = six.binary_type()

    def _packet_send(self, data):
        self._stream().raw_send_all(
                _length_to_bytes(len(data)) + data.encode())

    def _remote_call(self, name, args, kwargs):
        try:
            result = {
                'result': getattr(self._target, _RPC_PREFIX + name)(
                        *args, **kwargs),
            }
        except BaseException as exc:
            _log.exception('RPC call %r failed, sending exception string to '
                           'remote end', (name, args, kwargs))
            result = {
                'error': '%r' % exc,
            }
        self._packet_send(json.dumps(result))

    def _on_packet_recv(self, packet):
        call = json.loads(packet.decode())
        self._remote_call(**call)

    def on_raw_recv(self, data):
        self._buffer += data
        if len(self._buffer) >= _LENGTH_LENGTH:
            length = _bytes_to_length(self._buffer[:_LENGTH_LENGTH])
        else:
            return

        if len(self._buffer) >= (_LENGTH_LENGTH + length):
            packet = self._buffer[_LENGTH_LENGTH:_LENGTH_LENGTH + length]
            self._buffer = self._buffer[_LENGTH_LENGTH + length:]
            self._on_packet_recv(packet)


class Client(object):
    def __init__(self, stream):
        self._stream = stream

    def _packet_send(self, data):
        self._stream.raw_send_all(
                _length_to_bytes(len(data)) + data.encode())

    def _raw_recv_all(self, size):
        buf = six.binary_type()
        while size:
            chunk = self._stream.raw_recv(size)
            if not chunk:
                raise RuntimeError('Got unexpected EOF')
            buf += chunk
            size -= len(chunk)

        return buf

    def _packet_recv(self):
        length = _bytes_to_length(
                self._raw_recv_all(_LENGTH_LENGTH))
        return self._raw_recv_all(length).decode()

    def _remote_call(self, name, *args, **kwargs):
        self._packet_send(json.dumps({
            'name': name,
            'args': args,
            'kwargs': kwargs,
        }))
        result = json.loads(self._packet_recv())
        if 'error' in result:
            raise RuntimeError(
                    'RPC error %r -> %r' % ((name, args, kwargs), result))
        return result['result']

    def __getattr__(self, name):
        if not name.startswith(_RPC_PREFIX):
            raise KeyError('Attribute not found: %s' % name)

        remote_fn = functools.partial(
                self._remote_call, name[len(_RPC_PREFIX):])

        setattr(self, name, remote_fn)
        return remote_fn
