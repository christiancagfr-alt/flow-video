"""Hidden child processes; preserve captured output and JSON protocols."""
import os
import subprocess as _sp
from subprocess import *


def _options(kwargs):
    kwargs = dict(kwargs)
    if os.name == 'nt':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | _sp.CREATE_NO_WINDOW
    return kwargs


class Popen(_sp.Popen):
    def __init__(self, *args, **kwargs):
        kwargs = _options(kwargs)
        for name in ('stdin', 'stdout', 'stderr'):
            if kwargs.get(name) is None:
                kwargs[name] = _sp.DEVNULL
        super().__init__(*args, **kwargs)


def run(*args, **kwargs):
    kwargs = _options(kwargs)
    if not kwargs.get('capture_output'):
        for name in ('stdout', 'stderr'):
            if kwargs.get(name) is None:
                kwargs[name] = _sp.DEVNULL
    if kwargs.get('input') is None and kwargs.get('stdin') is None:
        kwargs['stdin'] = _sp.DEVNULL
    return _sp.run(*args, **kwargs)
