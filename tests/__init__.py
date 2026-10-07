import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))


def offline(url, *args, **kwargs):
    raise AssertionError(f"сеть в тестах запрещена: {getattr(url, 'full_url', url)}")


urllib.request.urlopen = offline
