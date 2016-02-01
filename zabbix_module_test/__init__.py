from __future__ import absolute_import

import zabbix_module.base as base


class Test(base.ModuleBase):
    def remote_item_list(self):
        return ({'key': 'pytest.ui64'},
                {'key': 'pytest.dbl'},
                {'key': 'pytest.str'},
                {'key': 'pytest.text'},
                {'key': 'pytest.msg'},
                {'key': 'pytest.fail'},
                {
                    'key': 'pytest.params',
                    'flags': ('haveparams', ),
                    'test_param': 'test_param',
                })

    def remote_get_value(self, key, *params):
        if key == 'pytest.ui64':
            return {'ui64': 42}
        elif key == 'pytest.dbl':
            return {'dbl': 3.14}
        elif key == 'pytest.str':
            return {'str': 'test string'}
        elif key == 'pytest.text':
            return {'text': 'test text'}
        elif key == 'pytest.msg':
            return {'msg': 'test message'}
        elif key == 'pytest.fail':
            return {'msg': 'test error message', 'result': False}
        elif key == 'pytest.params':
            if params:
                return {'text': 'Parameters: "' + '", "'.join(params) + '"'}
            else:
                return {'text': 'No parameters'}
