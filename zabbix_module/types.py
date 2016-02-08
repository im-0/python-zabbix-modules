from __future__ import absolute_import

import json

import six


class BaseStringValue(object):
    def __init__(self, format_string, *args, **kwargs):
        if (not args) and (not kwargs):
            self._str = format_string
        else:
            self._str = format_string.format(*args, **kwargs)

    def get_string(self):
        return self._str

    def __str__(self):
        return self._str


class Text(BaseStringValue):
    pass


class NotSupported(BaseStringValue):
    pass


class Discovery(object):
    def __init__(self, macros_list=None):
        if macros_list is None:
            self._macros_list = []
        else:
            self._macros_list = list(macros_list)

    def add_macros(self, macros_dict):
        self._macros_list.append(macros_dict)

    def get_string(self):
        return json.dumps({
            'data': list(
                    dict(('{#%s}' % name, value)
                         for name, value in six.iteritems(macros))
                    for macros in self._macros_list)
        })

    def __str__(self):
        return self.get_string()
