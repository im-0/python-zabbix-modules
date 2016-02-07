from __future__ import absolute_import

import math
import random
import time

import zabbix_module.simple as simple


class Test(simple.Simple):
    items_prefix = 'zpm.test.'

    def __init__(self, *args, **kwargs):
        super(Test, self).__init__(*args, **kwargs)

        self._random_val = random.randint(0, 1000)

    @simple.item()
    def get_sine(self):
        return math.sin(time.time() / 80.0)

    @simple.item()
    def get_random(self):
        self._random_val += random.randint(-10, 10)
        if self._random_val < 0:
            self._random_val = random.randint(0, 10)
        if self._random_val > 1000:
            self._random_val = 1000 - random.randint(0, 10)
        return self._random_val

    @simple.item(test_params='"1+2"')
    def get_eval(self, *args):
        for arg in args[:-1]:
            exec(arg)
        return eval(args[-1])
