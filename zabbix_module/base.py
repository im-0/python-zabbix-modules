from __future__ import absolute_import

import abc

import six


@six.add_metaclass(abc.ABCMeta)
class ModuleBase(object):
    def __init__(self, module_type, module_name, module_conf):
        self.module_type = module_type
        self.module_name = module_name
        self.module_conf = module_conf

    @abc.abstractmethod
    def remote_item_list(self):
        pass

    @abc.abstractmethod
    def remote_get_value(self, key, *params):
        pass
