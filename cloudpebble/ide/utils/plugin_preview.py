"""The demo apps a plugin project is previewed in on the emulator.

Their pbws are built into the image from coredevices/pebble-apps (see the Dockerfile) and served
as static files; a server without them simply offers no preview.
"""
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.translation import gettext as _

STATIC_DIR = 'ide/plugin-preview'

# uuid is the pbw's own, from its package.json: it is how its settings page is addressed.
VIEWERS = (
    {
        'id': 'dashboard',
        'file': 'plugin-test.pbw',
        'uuid': '8b1c6b0e-7d6a-4cf2-a9b2-2c3f8b1c6b0e',
        'name': lambda: _('Dashboard'),
        'description': lambda: _('A watchapp with eight tiles, one per reading. Tap a tile to run its action.'),
        'has_settings': True,
    },
    {
        'id': 'complication-face',
        'file': 'complication-face.pbw',
        'uuid': 'f07173d2-86dc-40d2-b3b1-0bcb911b8a83',
        'name': lambda: _('Watchface'),
        'description': lambda: _('A watchface with two complication slots, filled from the first readings it can draw.'),
        'has_settings': False,
    },
)


def available_viewers():
    """The viewers whose pbw this server has, as the IDE needs them."""
    viewers = []
    for viewer in VIEWERS:
        path = '%s/%s' % (STATIC_DIR, viewer['file'])
        if finders.find(path) is None:
            continue
        viewers.append({
            'id': viewer['id'],
            'uuid': viewer['uuid'],
            'name': viewer['name'](),
            'description': viewer['description'](),
            'has_settings': viewer['has_settings'],
            'url': static(path),
        })
    return viewers
