from __future__ import absolute_import

import os
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


def _get_field(field_n, conv=None):
    def _really_get_field(str_value):
        field_values = str_value.split()
        if (not str_value) or (len(field_values) <= field_n):
            return types.NotSupported(
                    'String "{0}" does not contain field #{1}',
                    str_value, field_n)

        field_value = field_values[field_n]

        if conv is None:
            return field_value
        else:
            return conv(field_value)

    return _really_get_field


class _Block(simple.Simple):
    """
    $KERNEL_SRC/Documentation/block/stat.txt
    """

    items_prefix = 'block.'

    @simple.item()
    def get_discovery(self):
        return types.Discovery({
            'ZPM_LINUX_BLOCK_DEV': block_dev_name,
        } for block_dev_name in os.listdir('/sys/class/block'))

    @simple.item(test_params='sda')
    def get_read_ios(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(0, int))

    @simple.item(test_params='sda')
    def get_read_merges(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(1, int))

    @simple.item(test_params='sda')
    def get_read_sectors(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(2, int))

    @simple.item(test_params='sda')
    def get_read_ticks(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(3, int))

    @simple.item(test_params='sda')
    def get_write_ios(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(4, int))

    @simple.item(test_params='sda')
    def get_write_merges(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(5, int))

    @simple.item(test_params='sda')
    def get_write_sectors(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(6, int))

    @simple.item(test_params='sda')
    def get_write_ticks(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(7, int))

    @simple.item(test_params='sda')
    def get_in_flight(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(8, int))

    @simple.item(test_params='sda')
    def get_io_ticks(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(9, int))

    @simple.item(test_params='sda')
    def get_time_in_queue(self, block_dev_name):
        return _read_file('/sys/class/block/%s/stat' % block_dev_name,
                          _get_field(10, int))


class Main(simple.Simple):
    items_prefix = 'zpm.linux.'

    def __init__(self, *args, **kwargs):
        super(Main, self).__init__(*args, **kwargs)

        self.add_submodule(_KSM(*args, **kwargs))
        self.add_submodule(_Block(*args, **kwargs))
