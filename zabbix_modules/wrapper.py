import collections


# Native Zabbix module will initialize these with real values.
ZBX_MODULE_OK = None
ZBX_MODULE_FAIL = None
CF_HAVEPARAMS = None
SYSINFO_RET_OK = None
SYSINFO_RET_FAIL = None


ZbxMetric = collections.namedtuple(
        'ZbxMetric', (
                'key',
                'flags',
                'test_param'))
AgentRequest = collections.namedtuple(
        'AgentRequest', (
                'key',
                'params',
                'mtime'))


class AgentResult(object):
    __slots__ = (
        'ui64',
        'dbl',
        'str',
        'text',
        'msg')

    def __init__(self):
        for slot_name in AgentResult.__slots__:
            setattr(self, slot_name, None)

    def __repr__(self):
        return repr(
                dict((slot_name, getattr(self, slot_name))
                     for slot_name in AgentResult.__slots__))


def init(module_type):
    return ZBX_MODULE_OK


def after_fork(parent):
    pass


def item_list():
    return (ZbxMetric('pytest.ui64',   0,             None),
            ZbxMetric('pytest.dbl',    0,             None),
            ZbxMetric('pytest.str',    0,             None),
            ZbxMetric('pytest.text',   0,             None),
            ZbxMetric('pytest.msg',    0,             None),
            ZbxMetric('pytest.fail',   0,             None),
            ZbxMetric('pytest.params', CF_HAVEPARAMS, 'test_param'))


def get_value(request, result):
    if request.key == 'pytest.ui64':
        result.ui64 = 42
    elif request.key == 'pytest.dbl':
        result.dbl = 3.14
    elif request.key == 'pytest.str':
        result.str = 'test string'
    elif request.key == 'pytest.text':
        result.text = 'test text'
    elif request.key == 'pytest.msg':
        result.msg = 'test message'
    elif request.key == 'pytest.fail':
        result.msg = 'test error message'
        return SYSINFO_RET_FAIL
    elif request.key == 'pytest.params':
        if request.params:
            result.text = 'Parameters: "' + '", "'.join(request.params) + '"'
        else:
            result.text = 'No parameters'

    return SYSINFO_RET_OK


def uninit():
    return ZBX_MODULE_OK
