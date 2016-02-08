from __future__ import absolute_import

import inspect

import six

import zabbix_module.base
import zabbix_module.types as types


_GET_FN_PREFIX = 'get_'


def _add_args_check(fn, argspec):
    max_args = len(argspec.args) - 1
    min_args = max_args
    if argspec.varargs is not None:
        max_args = None
    if argspec.defaults is not None:
        min_args -= len(argspec.defaults)
    if min_args < 0:
        raise RuntimeError('"self" argument with default value?')

    if (min_args == 0) and (max_args is None):
        return fn

    def _check_args(self_arg, *args):
        if len(args) < min_args:
            return types.NotSupported(
                    'Not enough arguments for item: {0} < {1}',
                    len(args), min_args)
        if (max_args is not None) and (len(args) > max_args):
            return types.NotSupported(
                    'Too many arguments for item: {0} > {1}',
                    len(args), max_args)
        return fn(self_arg, *args)

    return _check_args


def _add_converters(fn, argspec, arg_converters):
    if not arg_converters:
        return fn

    for arg_name in six.iterkeys(arg_converters):
        if arg_name not in argspec.args:
            raise RuntimeError('Unknown argument: "%s"' % arg_name)
    arg_converters = tuple(
            arg_converters.get(arg_name)
            for arg_name in argspec.args[1:])

    def _convert(self_arg, *args):
        return fn(self_arg,
                  *(arg if conv_fn is None else conv_fn(arg)
                    for conv_fn, arg in zip(arg_converters, args)))

    return _convert


def _item(fn, name=None, arg_converters=None, test_params=None):
    if name is None:
        if not fn.__name__.startswith(_GET_FN_PREFIX):
            raise RuntimeError(
                    'Unable to determine name of item, because name of '
                    'function does not start with "%s": "%s"' % (
                        _GET_FN_PREFIX, fn.__name__))
        name = fn.__name__[len(_GET_FN_PREFIX):]

    argspec = inspect.getargspec(fn)

    if not argspec.args:
        raise RuntimeError('Functions without "self" argument are not '
                           'supported')
    if argspec.keywords is not None:
        raise RuntimeError('Keyword arguments are not supported')

    fn = _add_converters(fn, argspec, arg_converters)
    fn = _add_args_check(fn, argspec)

    fn.item_name = name
    fn.have_params = (len(argspec.args) > 1) or (argspec.varargs is not None)

    if (test_params is None) or isinstance(test_params, six.string_types):
        fn.test_param = test_params
    else:
        fn.test_param = ','.join(test_params)

    return fn


def item(name=None, arg_converters=None, test_params=None):
    return lambda fn: _item(fn, name, arg_converters, test_params)


class Simple(zabbix_module.base.ModuleBase):
    items_prefix = ''

    def _add_item(self, item_name, fn):
        item_name = self.items_prefix + item_name
        if item_name in self._supported_items:
            raise RuntimeError('Duplicate item: "%s"' % item_name)
        self._supported_items[item_name] = fn

    def _add_supported_items(self):
        for self_member_name in dir(self):
            self_member = getattr(self, self_member_name)
            if hasattr(self_member, 'item_name'):
                self._add_item(self_member.item_name, self_member)

    def add_submodule(self, submodule):
        for item_name, fn in six.iteritems(submodule._supported_items):
            self._add_item(item_name, fn)

    def __init__(self, *args, **kwargs):
        super(Simple, self).__init__(*args, **kwargs)

        self._supported_items = {}
        self._add_supported_items()

    def remote_item_list(self):
        return [{
                    'key': key,
                    'flags': ('haveparams', ) if fn.have_params else (),
                    'test_param': fn.test_param,
                } for key, fn in six.iteritems(self._supported_items)]

    def remote_get_value(self, key, *params):
        result = self._supported_items[key](*params)
        if isinstance(result, six.integer_types):
            return {'ui64': result}
        elif isinstance(result, float):
            return {'dbl': result}
        elif isinstance(result, six.string_types):
            return {'str': result}
        elif isinstance(result, types.Text):
            return {'text': result.get_string()}
        elif isinstance(result, types.NotSupported):
            return {'msg': result.get_string(), 'result': False}
        elif isinstance(result, types.Discovery):
            return {'str': result.get_string()}
        else:
            raise RuntimeError(
                    'Item "%s" returned value of unknown type "%s": %r' % (
                        key, type(result).__name__, result))
