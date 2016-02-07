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
