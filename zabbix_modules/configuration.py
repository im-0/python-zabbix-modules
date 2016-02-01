from __future__ import absolute_import

import os
import os.path

import yaml


CONF = {}
CONF_FILE_PATH = None

MODULE_CONF_EXT = '.conf'


def _get_default(module_type):
    return {
        'log_file': os.path.join(
                '/', 'var', 'log', 'python_zabbix_modules',
                'zabbix_%s.log' % module_type),
        'log_level': 'info',
        'modules_conf_dir': os.path.join(
                '/', 'etc', 'python_zabbix_modules',
                'zabbix_%s.enabled.d' % module_type),
        'modules_sock_dir': os.path.join(
                '/', 'var', 'run', 'python_zabbix_modules.%s' % module_type),
    }


def _get_file_paths(module_type):
    return (
        os.environ.get('PYTHON_ZABBIX_%s_MODULES_CONF' % module_type.upper()),
        os.path.join('/', 'etc', 'python_zabbix_modules',
                     'zabbix_%s.conf' % module_type),
        os.path.join(os.path.expanduser('~'), '.config',
                     'python_zabbix_modules', 'zabbix_%s.conf' % module_type),
    )


def _find_file(module_type):
    for file_path in _get_file_paths(module_type):
        if file_path is None:
            continue
        if os.path.exists(file_path):
            return file_path
    raise RuntimeError(
            'Configuration file not found for "zabbix_%s"' % module_type)


def load(module_type):
    conf = _get_default(module_type)

    file_path = _find_file(module_type)
    with open(file_path) as conf_file:
        conf.update(yaml.safe_load(conf_file) or {})

    return conf, file_path


def load_global(module_type):
    global CONF, CONF_FILE_PATH
    conf, CONF_FILE_PATH = load(module_type)
    CONF.clear()
    CONF.update(conf)
