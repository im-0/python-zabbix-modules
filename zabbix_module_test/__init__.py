from __future__ import absolute_import

import zabbix_module.simple as simple
import zabbix_module.types as types


class Test(simple.Simple):
    items_prefix = 'pytest.'

    @simple.item()
    def get_ui64(self):
        return 42

    @simple.item()
    def get_dbl(self):
        return 1.45

    @simple.item()
    def get_str(self):
        return 'test string'

    @simple.item()
    def get_text(self):
        return types.Text('test string')

    @simple.item()
    def get_fail(self):
        return types.NotSupported('test error message')

    @simple.item()
    def get_params(self, *args):
        if args:
            return 'Parameters: "' + '", "'.join(args) + '"'
        else:
            return 'No parameters'
