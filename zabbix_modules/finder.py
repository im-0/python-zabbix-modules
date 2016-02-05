# -*- coding: utf-8 -*-

from __future__ import absolute_import

import json
import os
import sys

import stevedore


def main():
    namespace = sys.argv[1]
    manager = stevedore.ExtensionManager(namespace)
    json.dump(manager.names(), sys.stdout)
    return os.EX_OK


if __name__ == "__main__":
    sys.exit(main())
