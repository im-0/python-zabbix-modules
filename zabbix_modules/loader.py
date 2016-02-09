# -*- coding: utf-8 -*-

from __future__ import absolute_import

import functools
import os
import signal
import sys

import yaml

import stevedore

import trollius

import setproctitle

import zabbix_modules.configuration as configuration
import zabbix_modules.logging as logging
import zabbix_modules.modules as modules
import zabbix_modules.rpc as rpc


_conf = configuration.CONF
_log = None


class _ModuleServer(trollius.BaseProtocol):
    def __init__(self, target):
        super(_ModuleServer, self).__init__()
        self._rpc = rpc.Server(self, target)

    def connection_made(self, transport):
        _log.info('New connection accepted')
        self._transport = transport

    def data_received(self, data):
        self._rpc.on_raw_recv(data)

    def raw_send_all(self, data):
        try:
            self._transport.write(data)
        except:
            _log.exception('Unable to send RPC answer, ignoring')
            try:
                self._transport.close()
            except:
                _log.exception('Unable to close transport, ignoring')


    def eof_received(self):
        _log.info('EOF received')


def _get_default_loader_conf(module_name):
    return {
        'log_file': os.path.join('/', 'var', 'log', 'python_zabbix_modules',
                                 'module.%s.log' % module_name),
        'log_level': 'info',
    }


def _stop(sig_num, loop):
    _log.info('Exiting on signal %d...', sig_num)
    loop.stop()


def _main(namespace, module_type, module_name, module_conf):
    setproctitle.setproctitle(
            'python_zabbix_modules: Module %s/%s' % (module_type, module_name))

    _log.info('Loading module "%s"...', module_name)

    manager = stevedore.DriverManager(
            namespace, module_name, True,
            invoke_kwds=dict(
                    module_type=module_type,
                    module_name=module_name,
                    module_conf=module_conf))

    _log.info('Module "%s" loaded successfully, running...', module_name)

    try:
        loop = trollius.get_event_loop()

        for sig_num in signal.SIGINT, signal.SIGTERM:
            loop.add_signal_handler(sig_num, lambda: _stop(sig_num, loop))

        socket_path = modules.get_sock_path(_conf, module_type, module_name)
        module_coroutine = loop.create_unix_server(
                functools.partial(_ModuleServer, manager.driver), socket_path)
        loop.run_until_complete(module_coroutine)
        # Access to sockets will be restricted on directory level.
        os.chmod(socket_path, 0o666)

        try:
            loop.run_forever()
        finally:
            loop.close()
    finally:
        manager.driver.on_module_terminate()


def main():
    namespace, module_type, module_name = sys.argv[1:4]

    configuration.load_global(module_type)

    module_conf_path = modules.get_conf_path(_conf, module_name)
    with open(module_conf_path) as conf_file:
        module_conf = yaml.safe_load(conf_file) or {}
    loader_conf = _get_default_loader_conf(module_name)
    loader_conf.update(module_conf.get('loader', {}))

    global _log
    _log = logging.configure_file_logger(
            loader_conf['log_file'], loader_conf['log_level'])

    _log.info('Global configuration file: "%s"', configuration.CONF_FILE_PATH)
    _log.info('Module configuration file: "%s"', module_conf_path)

    try:
        _main(namespace, module_type, module_name,
              module_conf.get('module', {}))
    except KeyboardInterrupt:
        _log.info('Exiting after keyboard interrupt')
    except:
        _log.exception('Unhandled exception')
        return os.EX_SOFTWARE
    return os.EX_OK


if __name__ == "__main__":
    sys.exit(main())
