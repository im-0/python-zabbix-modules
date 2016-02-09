# -*- coding: utf-8 -*-

from __future__ import absolute_import

import grp
import functools
import json
import os
import os.path
import pwd
import signal
import subprocess
import sys
import time
import weakref

import yaml

import trollius

import zabbix_modules.configuration as configuration
import zabbix_modules.logging as logging
import zabbix_modules.modules as modules


_DEFAULT_CONF = {
    'log_file': os.path.join('/', 'var', 'log', 'python_zabbix_modules',
                             'manager.log'),
    'log_level': 'info',
    'python_interpreters_dir': os.path.join('/', 'etc',
                                            'python_zabbix_modules',
                                            'interpreters'),
    'credentials': {},
}

_CONF_FILE_PATHS = (
    os.environ.get('PYTHON_ZABBIX_MODULES_MANAGER_CONF'),
    os.path.join('/', 'etc', 'python_zabbix_modules', 'manager.conf'),
    os.path.join(os.path.expanduser('~'), '.config',
                 'python_zabbix_modules', 'manager.conf'),
)

_NAMESPACE = 'zabbix_modules'

_MODULES_FINDER = 'zabbix_modules.finder'
_MODULES_LOADER = 'zabbix_modules.loader'

_MODULE_TYPES = ('agent', 'agentd', 'server')

_MODULE_RESTART_SLEEP = 5.0  # seconds


_conf = _DEFAULT_CONF
_log = None


def _find_interpreters():
    interpreters = os.listdir(_conf['python_interpreters_dir'])
    if not interpreters:
        raise RuntimeError('No python interpreters configured')
    interpreters.sort()
    _log.info('Found %u python interpreters: %s',
              len(interpreters), ', '.join(interpreters))
    return interpreters


def _find_modules(interpreter):
    _log.info('Looking for installed modules using interpreter %s...',
              interpreter)

    proc = subprocess.Popen(
            (
                os.path.join(_conf['python_interpreters_dir'], interpreter),
                '-m', _MODULES_FINDER,
                _NAMESPACE
            ),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, _ = proc.communicate()
    if proc.returncode:
        raise RuntimeError(
                '"%s" exited with code %d' % (_MODULES_FINDER, proc.returncode))

    installed_modules = json.loads(stdout.decode())
    _log.info('%u installed modules found:', len(installed_modules))
    for installed_module in installed_modules:
        _log.info('"%s" (%s)', installed_module, interpreter)

    return installed_modules


def _find_module_interpreters():
    module_interpreters = {}
    for interpreter in _find_interpreters():
        for installed_module in _find_modules(interpreter):
            if installed_module in module_interpreters:
                _log.warning('Skipping duplicate module with different '
                             'interpreter: "%s" (%s)',
                             installed_module, interpreter)
                continue

            module_interpreters[installed_module] = interpreter

    _log.info('%u available modules', len(module_interpreters))
    return module_interpreters


def _get_credentials(module_type, credentials_name):
    credentials = _conf['credentials'].get(module_type, {}).get(
            credentials_name)
    if credentials is None:
        raise RuntimeError(
                'Undefined credentials "%s" for module type "%s"' % (
                    credentials_name, module_type))
    return credentials


def _normalize_credentials(module_type, credentials):
    credentials_name = credentials.get('credentials')
    if credentials_name is not None:
        credentials.update(_get_credentials(module_type, credentials_name))

    if 'user' in credentials:
        credentials['user_id'] = pwd.getpwnam(credentials['user']).pw_uid
    if 'group' in credentials:
        credentials['group_id'] = grp.getgrnam(credentials['group']).gr_gid


def _create_dirs(module_type, conf):
    _normalize_credentials(module_type, conf['modules_sock_dir_access'])
    user_id = conf['modules_sock_dir_access'].get('user_id', -1)
    group_id = conf['modules_sock_dir_access'].get('group_id', -1)
    mode = conf['modules_sock_dir_access'].get('mode')

    sock_dir = conf['modules_sock_dir']

    if mode is None:
        _log.info('Checking socket directory "%s" (%d:%d)',
             sock_dir, user_id, group_id)
    else:
        _log.info('Checking socket directory "%s" (%d:%d, 0o%o)',
             sock_dir, user_id, group_id, mode)

    if not os.path.exists(sock_dir):
        os.mkdir(sock_dir, mode or 0o700)

    # Ensure right permissions on already existing directory.
    if mode is not None:
        os.chmod(sock_dir, mode)
    os.chown(sock_dir, user_id, group_id)


def _find_enabled_modules(module_type):
    conf, _ = configuration.load(module_type)
    _create_dirs(module_type, conf)
    return [(
                module_name,
                modules.get_sock_path(conf, module_type, module_name),
                modules.get_conf_path(conf, module_name),
            )
            for module_name in modules.find_enabled(conf)]


def _get_module_runas(module_type, module_conf_path):
    with open(module_conf_path) as conf_file:
        module_conf = yaml.safe_load(conf_file) or {}
    module_manager_conf = module_conf.get('manager', {})
    module_runas = module_manager_conf.get('runas', {})
    _normalize_credentials(module_type, module_runas)
    return module_runas


def _find_all_enabled_modules():
    enabled_modules = []
    for module_type in _MODULE_TYPES:
        enabled_modules.extend(
                [(
                     module_type,
                     module_name,
                     module_socket_path,
                     _get_module_runas(module_type, module_conf_path),
                 )
                 for module_name, module_socket_path, module_conf_path
                 in _find_enabled_modules(module_type)])

    return enabled_modules


class _ModuleProcess(trollius.SubprocessProtocol):
    def __init__(self, loop, module_type, module_name, module_interpreter,
                 module_socket_path, module_runas):
        super(_ModuleProcess, self).__init__()

        self._loop = weakref.ref(loop)
        self._module_type = module_type
        self._module_name = module_name
        self._module_interpreter = module_interpreter
        self._module_socket_path = module_socket_path
        self._module_runas = module_runas

    def process_exited(self):
        _log.error('Plugin "%s/%s" (%s) exited, restarting...',
                   self._module_type, self._module_name,
                   self._module_interpreter)
        # TODO: Asynchronous sleep.
        time.sleep(_MODULE_RESTART_SLEEP)
        _spawn_process(self._loop(),
                       self._module_type,
                       self._module_name,
                       self._module_interpreter,
                       self._module_socket_path,
                       self._module_runas)


def _runas(user_id, group_id):
    if group_id != -1:
        os.setgid(group_id)
    if user_id != -1:
        os.setuid(user_id)


def _spawn_process(loop, module_type, module_name, module_interpreter,
                   module_socket_path, module_runas):
    user_id = module_runas.get('user_id', -1)
    group_id = module_runas.get('group_id', -1)

    if ((user_id != -1) or (group_id != -1)) and (os.getuid() != 0):
        raise RuntimeError('"runas" only available for root')

    _log.info('Starting module "%s/%s" (%s) as %d:%d',
              module_type, module_name, module_interpreter, user_id, group_id)

    if os.path.exists(module_socket_path):
        os.unlink(module_socket_path)

    process = loop.subprocess_exec(
            functools.partial(
                    _ModuleProcess,
                    loop, module_type, module_name, module_interpreter,
                    module_socket_path, module_runas),
            os.path.join(_conf['python_interpreters_dir'], module_interpreter),
            '-m', _MODULES_LOADER,
            _NAMESPACE, module_type, module_name,
            stdin=None, stdout=None, stderr=None,
            preexec_fn=functools.partial(_runas, user_id, group_id))
    if loop.is_running():
        loop.create_task(process)
    else:
        loop.run_until_complete(process)


def _stop(sig_num, loop):
    _log.info('Exiting on signal %d...', sig_num)
    loop.stop()


def _main():
    module_interpreters = _find_module_interpreters()

    enabled_modules = []
    for mod_type, mod_name, mod_socket_path, mod_runas in \
            _find_all_enabled_modules():
        module_interpreter = module_interpreters.get(mod_name)
        if module_interpreter is None:
            raise RuntimeError('Unable to find right interpreter for module '
                               '"%s"' % mod_name)
        enabled_modules.append(
                (mod_type, mod_name, module_interpreter, mod_socket_path,
                 mod_runas))

    _log.info('%u enabled module instances found', len(enabled_modules))

    loop = trollius.get_event_loop()

    for sig_num in signal.SIGINT, signal.SIGTERM:
        loop.add_signal_handler(sig_num, lambda: _stop(sig_num, loop))

    list(map(lambda module: _spawn_process(loop, *module), enabled_modules))

    try:
        loop.run_forever()
    finally:
        loop.close()


def _find_conf_file():
    for file_path in _CONF_FILE_PATHS:
        if file_path is None:
            continue
        if os.path.exists(file_path):
            return file_path
    raise RuntimeError('Configuration file for manager not found')


def _load_conf(file_path):
    global _conf

    with open(file_path) as conf_file:
        _conf.update(yaml.safe_load(conf_file) or {})


def main():
    conf_file_path = _find_conf_file()
    _load_conf(conf_file_path)

    global _log
    _log = logging.configure_file_logger(_conf['log_file'], _conf['log_level'])

    _log.info('Manager started')
    _log.info('Configuration file: "%s"', conf_file_path)

    try:
        _main()
    except KeyboardInterrupt:
        _log.info('Exiting after keyboard interrupt')
    except:
        _log.exception('Unhandled exception')
        return os.EX_SOFTWARE
    # TODO: Ensure that all subprocesses are killed.
    return os.EX_OK


if __name__ == "__main__":
    sys.exit(main())
