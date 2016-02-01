from __future__ import absolute_import

import collections
import socket
import time

import zabbix_modules.configuration as configuration
import zabbix_modules.logging as logging
import zabbix_modules.modules as modules
import zabbix_modules.rpc as rpc


# Native Zabbix module will initialize these with real values.
ZBX_MODULE_OK = None
ZBX_MODULE_FAIL = None
CF_HAVEPARAMS = None
SYSINFO_RET_OK = None
SYSINFO_RET_FAIL = None


_SOCKET_CONNECTION_TIMEOUT = 4.0  # seconds

_MODULE_CONNECTION_RETRY_SLEEP = 5.0  # seconds


_conf = configuration.CONF
_log = None

_modules = []
_items = {}


class ZbxMetric(collections.namedtuple(
        'ZbxMetric', (
                'key',
                'flags',
                'test_param'))):

    @staticmethod
    def _get_supported_flags():
        # Constants will be initialized after module loading.
        try:
            return ZbxMetric._supported_flags
        except AttributeError:
            ZbxMetric._supported_flags = {
                'haveparams': CF_HAVEPARAMS,
            }
            return ZbxMetric._supported_flags

    def __new__(cls, from_dict):
        key = from_dict['key']

        flags = 0
        flags_strings = set(from_dict.get('flags', ()))
        while flags_strings:
            flag_string = flags_strings.pop()
            flag_val = cls._get_supported_flags().get(flag_string)
            if flag_val is None:
                raise RuntimeError('Unknown item flag: "%s" (key "%s")' % (
                    flag_string, key))
            flags |= flag_val

        return super(cls, ZbxMetric).__new__(
                cls, key, flags, from_dict.get('test_param'))


AgentRequest = collections.namedtuple(
        'AgentRequest', (
                'key',
                'params',
                'mtime'))


class AgentResult(object):
    __slots__ = (
        'ui64',
        'dbl',
        'str',
        'text',
        'msg')

    def __init__(self):
        for slot_name in AgentResult.__slots__:
            setattr(self, slot_name, None)

    def __repr__(self):
        return repr(
                dict((slot_name, getattr(self, slot_name))
                     for slot_name in AgentResult.__slots__))

    def fill_from_dict(self, result_dict):
        for slot_name in AgentResult.__slots__:
            if slot_name in result_dict:
                setattr(self, slot_name, result_dict[slot_name])


class _ModuleConnectionError(RuntimeError):
    pass


class _ModuleClient(object):
    def __init__(self, module_type, module_name):
        self.module_name = module_name

        self._sock_path = modules.get_sock_path(_conf, module_type, module_name)

        self._sock = None

    def socket_close(self):
        if self._sock is None:
            return

        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        finally:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _socket_connect(self):
        _log.info('Connecting to "%s"...', self._sock_path)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        self._sock.settimeout(_SOCKET_CONNECTION_TIMEOUT)
        try:
            self._sock.connect(self._sock_path)
        except socket.error as exc:
            _log.error('Connection to "%s" failed: %r', self._sock_path, exc)
            self.socket_close()
        else:
            self._sock.settimeout(None)
            _log.info('Successfully connected to "%s"', self._sock_path)

    def socket_touch(self):
        if self._sock is not None:
            return
        self._socket_connect()
        if self._sock is None:
            raise _ModuleConnectionError(
                    'Connection to %s failed, will try again '
                    'later' % self._sock_path)

    def raw_send_all(self, data):
        self.socket_touch()

        try:
            self._sock.sendall(data)
        except:
            self.socket_close()
            raise

    def raw_recv(self, buf_size):
        self.socket_touch()

        try:
            return self._sock.recv(buf_size)
        except:
            self.socket_close()
            raise


class _Module(rpc.Client):
    def __init__(self, connection, module_name):
        super(_Module, self).__init__(connection)

        self.name = module_name


def _init(module_type):
    _log.info('Initializing (zabbix_%s)...' % module_type)
    _log.info('Configuration file: "%s"', configuration.CONF_FILE_PATH)

    _log.info('Locating modules...')
    for module_name in modules.find_enabled(_conf):
        _log.info('Found enabled module "%s"', module_name)
        client = _ModuleClient(module_type, module_name)
        module = _Module(client, module_name)
        _modules.append((client, module))
    _log.info('Found %u modules', len(_modules))


def init(module_type):
    configuration.load_global(module_type)

    global _log
    _log = logging.configure_file_logger(_conf['log_file'], _conf['log_level'])

    try:
        _init(module_type)
    except:
        _log.exception('Initialization failed')
        return ZBX_MODULE_FAIL

    return ZBX_MODULE_OK


def after_fork(parent):
    _log.info('Fork detected (parent == %r), resetting client sockets...',
              parent)
    for module_connection, _ in _modules:
        module_connection.socket_close()


def _module_item_list(module_connection, module):
    _log.info('Retrieving item list for module "%s"...', module.name)

    # Ensure successful connection to module.
    while True:
        try:
            module_connection.socket_touch()
        except _ModuleConnectionError:
            _log.warning(
                    'Connection to module "%s" failed, sleeping and '
                    'retrying...', module.name)
            time.sleep(_MODULE_CONNECTION_RETRY_SLEEP)
            continue
        break

    items = list(map(ZbxMetric, module.remote_item_list()))
    _log.info('Found %u items for module "%s":', len(items), module.name)
    for item in items:
        _log.info('%r', item)
    return items


def item_list():
    _log.info('Creating list of supported items...')

    for module_connection, module in _modules:
        try:
            module_items = _module_item_list(module_connection, module)
        except:
            _log.exception('Retrieving supported items failed for module "%s"',
                           module.name)
            continue

        for item in module_items:
            if item.key in _items:
                _log.error('Duplicate item key "%s" for module "%s", '
                           'skipping module', item.key, module.name)
                module_items = None
        if module_items is None:
            continue

        for item in module_items:
            _items[item.key] = module
            yield item

    _log.info('Total number of supported items: %u', len(_items))


def get_value(request, result):
    ret = SYSINFO_RET_OK

    key = request.key

    if key not in _items:
        raise RuntimeError('Unknown key: "%s"' % key)

    module = _items[key]
    try:
        result_dict = module.remote_get_value(key, *request.params)
        result.fill_from_dict(result_dict)
        if not result_dict.get('result', True):
            ret = SYSINFO_RET_FAIL
    except:
        _log.exception('Unable to get item "%s" from module "%s"',
                       key, module.name)
        result.msg = 'Unable to get item "%s" from module "%s", see log for ' \
                     'details' % (key, module.name)
        ret = SYSINFO_RET_FAIL

    return ret


def uninit():
    global _modules, _items
    _modules = []
    _items = {}

    return ZBX_MODULE_OK
