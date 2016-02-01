from __future__ import absolute_import

import logging
import os
import os.path

import zabbix_modules.configuration as configuration


_log = logging.getLogger(__name__)


def find_enabled(conf):
    for file_name in os.listdir(conf['modules_conf_dir']):
        if not file_name.endswith(configuration.MODULE_CONF_EXT):
            _log.warning('Ignoring module configuration file with invalid '
                         'name: "%s"',
                         file_name)
            continue
        module_name = file_name[:-len(configuration.MODULE_CONF_EXT)]
        if not module_name:
            _log.warning('Ignoring module configuration file with empty '
                         'module name: "%s"',
                         file_name)
            continue

        yield module_name


def get_conf_path(conf, module_name):
    return os.path.join(conf['modules_conf_dir'], module_name + '.conf')


def get_sock_path(conf, module_type, module_name):
    return os.path.join(
            conf['modules_sock_dir'], '%s.%s.sock' % (module_type, module_name))
