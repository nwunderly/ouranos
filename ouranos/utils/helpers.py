import datetime
import logging
import sys

logger = logging.getLogger('utils.helpers')


def list_by_category(guild):
    channels = []
    for category, category_channels in guild.by_category():
        if category is not None:
            channels.append(category)
        for channel in category_channels:
            channels.append(channel)
    return channels


def setup_logger(name, level):
    _logger = logging.getLogger(name)
    d = datetime.datetime.now()
    time = f"{d.month}-{d.day}_{d.hour}h{d.minute}m"

    filename = './logs/{}.log'

    file_handler = logging.FileHandler(filename.format(time))
    # file_handler.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stdout)
    # stream_handler.setLevel(level)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    _logger.addHandler(file_handler)
    _logger.addHandler(stream_handler)
    _logger.setLevel(level)
    return _logger


def approximate_timedelta(dt):
    if isinstance(dt, datetime.timedelta):
        dt = dt.total_seconds()
    s = lambda n: 's' if n != 1 else ''
    if dt >= WEEK:
        t = f"{(_w := dt // WEEK)} week" + s(_w)
        dt -= _w*WEEK
    elif dt >= DAY:
        t = f"{(_d := dt // DAY)} day" + s(_d)
        dt -= _d*DAY
    elif dt >= HOUR:
        t = f"{(_h := dt // HOUR)} hour" + s(_h)
        dt -= _h*HOUR
    elif dt >= MINUTE:
        t = f"{(_m := dt // MINUTE)} minute" + s(_m)
        dt -= _m*MINUTE
    else:
        t = f"{(_s := dt // SECOND)} second" + s(_s)
        dt -= _s*SECOND

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
        t.append(f"{(_w := dt // WEEK)} week" + s(_w))
        dt -= _w*WEEK
    if dt >= DAY:
        t.append(f"{(_d := dt // DAY)} day" + s(_d))
        dt -= _d*DAY
    if dt >= HOUR:
        t.append(f"{(_h := dt // HOUR)} hour" + s(_h))
        dt -= _h*HOUR
    if dt >= MINUTE:
        t.append(f"{(_m := dt // MINUTE)} minute" + s(_m))
        dt -= _m*MINUTE
    if dt >= SECOND:
        t.append(f"{(_s := dt // SECOND)} second" + s(_s))
        dt -= _s*SECOND

    return ", ".join(t)
