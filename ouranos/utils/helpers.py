import datetime
import logging
import sys

from logging.handlers import TimedRotatingFileHandler


logger = logging.getLogger('utils.helpers')


def list_by_category(guild):
    channels = []
    for category, category_channels in guild.by_category():
        if category is not None:
            channels.append(category)
        for channel in category_channels:
            channels.append(channel)
    return channels


def setup_logger(name, level, stream):
    _logger = logging.getLogger(name)

    filename = f'./logs/{name}.log'

    file_handler = TimedRotatingFileHandler(filename=filename, when='midnight', backupCount=14)
    # file_handler.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stdout)
    # stream_handler.setLevel(level)

    formatter = logging.Formatter('{asctime} - {levelname:7} - {name:22} - {message}', style='{')
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    _logger.addHandler(file_handler)
    if stream:
        _logger.addHandler(stream_handler)
    _logger.setLevel(level)

    return _logger


def approximate_timedelta(dt):
    if isinstance(dt, datetime.timedelta):
        dt = dt.total_seconds()
    s = lambda n: 's' if n != 1 else ''
    if dt >= WEEK:
        t = f"{int(_w := dt // WEEK)} week" + s(_w)
    elif dt >= DAY:
        t = f"{int(_d := dt // DAY)} day" + s(_d)
    elif dt >= HOUR:
        t = f"{int(_h := dt // HOUR)} hour" + s(_h)
    elif dt >= MINUTE:
        t = f"{int(_m := dt // MINUTE)} minute" + s(_m)
    else:
        t = f"{int(_s := dt // SECOND)} second" + s(_s)

    return t


SECOND = 1
MINUTE = SECOND*60
HOUR = MINUTE*60
DAY = HOUR*24
WEEK = DAY*7


def exact_timedelta(dt):
    if isinstance(dt, datetime.timedelta):
        dt = dt.total_seconds()
    t = []
    s = lambda n: 's' if n > 1 else ''
    if dt >= WEEK:
        t.append(f"{int(_w := dt // WEEK)} week" + s(_w))
        dt -= _w*WEEK
    if dt >= DAY:
        t.append(f"{int(_d := dt // DAY)} day" + s(_d))
        dt -= _d*DAY
    if dt >= HOUR:
        t.append(f"{int(_h := dt // HOUR)} hour" + s(_h))
        dt -= _h*HOUR
    if dt >= MINUTE:
        t.append(f"{int(_m := dt // MINUTE)} minute" + s(_m))
        dt -= _m*MINUTE
    if dt >= SECOND:
        t.append(f"{int(_s := dt // SECOND)} second" + s(_s))
        dt -= _s*SECOND

    return ", ".join(t)
