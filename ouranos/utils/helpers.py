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
    if dt.days >= 7:
        delta = f"{(_w := dt.days // 7)} week" + ('s' if _w > 1 else '')
    elif dt.days >= 1:
        delta = f"{(_d := dt.days)} day" + ('s' if _d > 1 else '')
    elif dt.seconds > 3599:
        delta = f"{(_h := dt.seconds // 3600)} hour" + ('s' if _h > 1 else '')
    elif dt.seconds > 59:
        delta = f"{(_m := dt.seconds // 60)} minute" + ('s' if _m > 1 else '')
    else:
        delta = f"{dt.seconds} seconds"

    return delta


def exact_timedelta(dt):
    t = []
    if dt.days >= 7:
        t.append(f"{(_w := dt.days // 7)} week" + ('s' if _w > 1 else ''))
    elif dt.days >= 1:
        t.append(f"{(_d := dt.days)} day" + ('s' if _d > 1 else ''))
    elif dt.seconds > 3599:
        t.append(f"{(_h := dt.seconds // 3600)} hour" + ('s' if _h > 1 else ''))
    elif dt.seconds > 59:
        t.append(f"{(_m := dt.seconds // 60)} minute" + ('s' if _m > 1 else ''))
    else:
        t.append(f"{dt.seconds} seconds")

    return ", ".join(t)
