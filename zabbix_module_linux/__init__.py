from __future__ import absolute_import

import os.path

import zabbix_module.simple as simple
import zabbix_module.types as types


def _read_file(file_path, conv=None):
    if not os.path.exists(file_path):
        return types.NotSupported('{0} does not exist', file_path)
    with open(file_path) as value_file:
        if conv is None:
            return value_file.read()
        else:
            return conv(value_file.read())


class _KSM(simple.Simple):
    """
    $KERNEL_SRC/Documentation/vm/ksm.txt
    """

    items_prefix = 'ksm.'

    @simple.item()
    def get_pages_shared(self):
        return _read_file('/sys/kernel/mm/ksm/pages_shared', int)

    @simple.item()
    def get_pages_sharing(self):
        return _read_file('/sys/kernel/mm/ksm/pages_sharing', int)

    @simple.item()
    def get_pages_unshared(self):
        return _read_file('/sys/kernel/mm/ksm/pages_unshared', int)

    @simple.item()
    def get_pages_volatile(self):
        return _read_file('/sys/kernel/mm/ksm/pages_volatile', int)

    @simple.item()
    def get_full_scans(self):
        return _read_file('/sys/kernel/mm/ksm/full_scans', int)


class Main(simple.Simple):
    items_prefix = 'zpm.linux.'

    def __init__(self, *args, **kwargs):
        super(Main, self).__init__(*args, **kwargs)

        self.add_submodule(_KSM(*args, **kwargs))
