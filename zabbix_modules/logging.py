from __future__ import absolute_import

import logging


def _configure_logger(**kwargs):
    root_logger = logging.getLogger()
    list(map(root_logger.removeHandler, root_logger.handlers[:]))
    list(map(root_logger.removeFilter, root_logger.filters[:]))
    logging.basicConfig(
        format=' %(levelname).1s|%(asctime)s|%(process)d:%(thread)d| '
               '%(message)s',
        **kwargs)
    return logging.getLogger()


def _get_log_level(level_str):
    return {
        'D': logging.DEBUG,
        'I': logging.INFO,
        'W': logging.WARNING,
        'E': logging.ERROR,
        'C': logging.CRITICAL,
    }[level_str.upper()[0]]


def configure_file_logger(log_file_path, level_str):
    return _configure_logger(
        filename=log_file_path,
        level=_get_log_level(level_str))
